"""The commands the Dependency proof and Dependency scan workflows run."""

from dependency_proof import prove, scan


def main(argv: list[str]) -> int:
    command = argv[0]
    if command == "scan-report":
        return scan.report()
    if command == "scan-gate":
        return scan.gate()
    return prove.main()
