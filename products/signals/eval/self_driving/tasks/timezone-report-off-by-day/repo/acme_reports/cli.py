from .data import sample_store
from .emailer import send_report_email
from .reports import generate_daily_report


def main() -> None:
    store = sample_store()
    for account in store.accounts():
        report = generate_daily_report(store, account)
        send_report_email(account, report)


if __name__ == "__main__":
    main()
