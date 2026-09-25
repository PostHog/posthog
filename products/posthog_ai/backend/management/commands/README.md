# Turn suggestion benchmark

`turn_suggestions_benchmark` scores the turn suggestion judge against labeled PostHog AI turns.
Use it to check a prompt change, a new show threshold, or a new System One model before it reaches users.

The cases live in [`turn_suggestions/benchmark_cases.yaml`](../../turn_suggestions/benchmark_cases.yaml).
Each case is an invented turn with the offers that would be a good outcome.
The file header explains the case format.

## Before you start

The command calls Jev the way production does: through the ai-gateway when `AI_GATEWAY_URL` and `AI_GATEWAY_API_KEY` are set, and through TypeSafe with `TYPESAFE_API_KEY` otherwise.
Set them in the environment or in `.env.local` at the repo root.
The two serve different Jev models, and the judge's label names the one that answered.
Other endpoints need neither, so `--skip-jev` runs without them.

Every run sends the invented cases to the judge. It sends no data from your local database.

## Run it

```sh
python manage.py turn_suggestions_benchmark
```

With no endpoints configured, the command judges every case with Jev and prints:

1. One line per case, as each answer arrives: the offer the judge picked, the show probability, the offer probabilities, and the time the request took.
2. The show probabilities grouped by label, so you can see how far apart the "should offer" and "should not offer" cases sit.
3. A sweep of show thresholds from 0.20 to 0.90, with the current threshold and the best F1 marked.
4. The threshold closest to the target offer rate (see [Target offer rate](#target-offer-rate)).

Run a subset while you iterate:

```sh
python manage.py turn_suggestions_benchmark --category diagnostic --category recurring_metric
python manage.py turn_suggestions_benchmark --case signups --state
```

## Compare Jev with other endpoints

List other System One endpoints in `TURN_SUGGESTIONS_BENCHMARK_ENDPOINTS`, in the environment or in `.env.local`.
With at least one endpoint, the command judges the cases with Jev and with every endpoint, then compares them.

Each entry is a URL:

```text
http[s]://[username:password@]host[:port][/path][#model]
```

- The credentials, when present, go out as HTTP basic auth.
- The path defaults to `/v1/systemone`.
- The part after `#` names the model to send in the request body. Without it, the request names no model. A URL fragment never reaches the server.
- Separate entries with spaces, commas, or semicolons.
- Percent-encode a `:`, `@`, or `#` inside a username or password, for example `%40` for `@`.

```sh
TURN_SUGGESTIONS_BENCHMARK_ENDPOINTS="https://user:secret@judge.example.com#candidate-1, https://user:secret@judge.example.com#candidate-2"
```

`.env.local` is gitignored, so it is the right place for credentials.
Do not pass credentials in `--endpoint`, because the shell keeps them in its history.

To choose the judges for one run:

- `--endpoint URL` judges with that URL instead of the variable. Repeat it to add more.
- `--skip-jev` judges with the endpoints only.
- `--jev-only` ignores the variable and judges with Jev alone, which gives the single-judge output above.

An endpoint must accept the same request body as TypeSafe's `POST /v1/systemone` and return answers in the same shape.
Endpoint requests skip the TypeSafe egress budget and its metrics, because they do not go to TypeSafe.

### Read the comparison

The command runs one judge at a time and prints one progress line for each judge.
When requests fail, it prints each distinct error once with its count, for example `9x HTTP 400: {"error": ...}`.
A judge that answers no case at all is left out of the tables.

**Scores at the show threshold.** Every judge at the same `--threshold`:

| Column     | Meaning                                                                |
| ---------- | ---------------------------------------------------------------------- |
| failed     | Cases where the request failed                                         |
| offer rate | Share of judged cases that get a card                                  |
| precision  | Share of cards that were a good pick                                   |
| recall     | Share of "should offer" cases that got a good card                     |
| F1         | The balance of precision and recall                                    |
| best F1    | The best F1 across the sweep, and the threshold that gets it           |
| agrees     | Share of cases where the judge picks the same offer as the first judge |
| median     | Median request time                                                    |

**Closest to the target offer rate.** Each judge at its own threshold for the target rate, with false offers, misses, and wrong kinds counted.
Compare judges here, because two models can put their show probabilities in different ranges.
At one shared threshold, a model that scores everything lower offers less often, and its precision is not comparable.

**Cases where the judges pick differently.** Only the cases where the judges disagree, each judge at its threshold for the target rate.
A failed request alone does not add a row.

| Mark | Meaning                                                                 |
| ---- | ----------------------------------------------------------------------- |
| ✓    | A good pick                                                             |
| ✗    | A card on a "should not offer" case, a miss, or the wrong kind of offer |
| ~    | A borderline case, and the pick is one of its acceptable outcomes       |
| !    | The request failed                                                      |

The number after the offer is the show probability.

`--sweep` also prints the full threshold sweep for every judge.

## Target offer rate

`--target-offer-rate` (default 0.45) finds the show threshold whose offer rate lands closest to the target.
It checks thresholds in steps of 0.01, and a tie goes to the higher threshold, which shows fewer cards.

This is a different question from best F1.
Best F1 finds the threshold with the best balance of precision and recall, whatever offer rate that gives.
The target search finds the threshold that offers as often as you want, whatever the quality there.

A threshold can only change how often a card shows.
It cannot fix the wrong kind of offer, because the judge picks the offer in a separate question.
If a judge cannot reach the target at any threshold, the closest threshold shows the highest rate it can reach.

## Options

| Option                | Default              | Effect                                                                                                              |
| --------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `--threshold`         | the production value | The show threshold for the per-case lines and the first scores table                                                |
| `--target-offer-rate` | 0.45                 | The offer rate to match, as a share between 0 and 1                                                                 |
| `--case NAME`         | all                  | Only cases whose name contains this text. Repeat it for more                                                        |
| `--category NAME`     | all                  | Only cases in this category. Repeat it for more                                                                     |
| `--workers`           | 8                    | Parallel requests per judge                                                                                         |
| `--cases-file`        | the bundled file     | Another YAML file with cases                                                                                        |
| `--state`             | off                  | Print the masked state the judge reads for each case. One judge only                                                |
| `--draft`             | off                  | Also ask the language model to write the scout or notebook text. Needs a team in the local database. One judge only |
| `--endpoint URL`      | the variable         | Judge with this URL instead of `TURN_SUGGESTIONS_BENCHMARK_ENDPOINTS`                                               |
| `--skip-jev`          | off                  | Judge with the endpoints only                                                                                       |
| `--jev-only`          | off                  | Ignore the endpoints and judge with Jev alone                                                                       |
| `--sweep`             | off                  | With more than one judge, print every judge's full sweep                                                            |

## Things to keep in mind

- Jev does not give the same probabilities on every run. The same prompt can move a case by about 0.05. Run twice before you trust a change that moves one or two cases.
- The prompts are tuned on these same cases, so a good score here is not proof of a good score on real traffic.
- The case file has more "should offer" cases than real traffic, so a threshold offers less often in production than it does here.
- Several judges share the same prompts. A prompt change that helps one model can hurt another, so compare every judge before you keep a change.
- A new case must be written from scratch with invented names and ids. Do not paste real conversations, even with names changed.
