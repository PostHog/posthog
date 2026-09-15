# Signals

Signals turns findings from many products and integrations into grouped reports that an autonomous coding agent can research and act on.
This glossary fixes the words for the safety layer, where three different things were all being called "the safety check".

## Language

### Safety

**Safety filter**:
The per-signal classifier that runs before signals are flushed to grouping.
It decides whether a single signal is manipulation and drops it if so.
_Avoid_: security check, safety check, safety classifier, safety judge

**Report safety judge**:
The per-report check that runs before repository selection and research, over all of a report's signals together.
_Avoid_: safety filter, report filter

**Safety-filter judge**:
The scout that re-grades each block after the fact as a true positive, false positive, or uncertain, and feeds the safety filter dashboard.
_Avoid_: the judge, the scout judge, the FP judge

**Manipulation**:
Content that tries to override the coding agent's operating rules or steer it into a harmful action the deployer did not ask for: exfiltration of sandbox secrets, execution of remote code, disabling review, fake system or authority messages, or hidden and encoded payloads.
Addressing the agent, giving it instructions, or discussing security are not manipulation on their own; the deployer's own tickets, briefs, and error strings do all three.
The safety filter blocks manipulation and nothing else.
_Avoid_: prompt injection (narrower), security-weakening request, suspicious content, instruction injection

**Security-sensitive signal**:
A signal whose requested change touches authentication, secrets, permissions, or network boundaries, written in good faith.
It passes the safety filter; human review of the resulting PR is the control.
_Avoid_: security-weakening request, security risk

**Block**:
A signal the safety filter dropped, with the threat type and explanation the filter gave.
_Avoid_: rejection, flag, drop

**False positive**:
A block of a signal that is not manipulation.
_Avoid_: false flag, over-block

**False-positive rate**:
The share of decided blocks the safety-filter judge calls false positives, so a measure of the filter's precision, not its recall.
_Avoid_: error rate, accuracy
