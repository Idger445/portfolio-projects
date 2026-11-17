"""Консольный учёт расходов в белорусских рублях."""

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
import json
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile


DEFAULT_FILE = Path(__file__).resolve().with_name("expenses.json")


@dataclass(frozen=True)
class Expense:
    date: str
    category: str
    amount_kopecks: int
    note: str = ""


def parse_amount(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)(?:[.,]([0-9]{1,2}))?", value)
    if not match:
        raise argparse.ArgumentTypeError("укажите сумму в формате 12,50 или 12.50")
    rubles, kopecks = match.groups()
    try:
        amount = int(rubles) * 100 + int((kopecks or "").ljust(2, "0"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("сумма слишком велика") from error
    if amount <= 0:
        raise argparse.ArgumentTypeError("сумма должна быть больше нуля")
    return amount


def parse_date(value: str) -> str:
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("укажите календарную дату в формате ГГГГ-ММ-ДД")


def parse_month(value: str) -> str:
    try:
        parse_date(f"{value}-01")
    except argparse.ArgumentTypeError as error:
        raise argparse.ArgumentTypeError("укажите месяц в формате ГГГГ-ММ") from error
    return value


def parse_category(value: str) -> str:
    category = " ".join(value.lower().split())
    if not category or not category.isprintable():
        raise argparse.ArgumentTypeError("укажите название категории")
    return category


def parse_note(value: str) -> str:
    note = value.strip()
    if note and not note.isprintable():
        raise argparse.ArgumentTypeError("укажите комментарий в одну строку")
    return note


def read_expenses(path: Path) -> list[Expense]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []

    records = json.loads(raw)
    if not isinstance(records, list):
        raise ValueError("хранилище должно содержать список расходов")

    expenses = []
    for number, record in enumerate(records, start=1):
        try:
            expense = Expense(**record)
            if type(expense.amount_kopecks) is not int or expense.amount_kopecks <= 0:
                raise ValueError("неверная сумма")
            expenses.append(Expense(
                parse_date(expense.date),
                parse_category(expense.category),
                expense.amount_kopecks,
                parse_note(expense.note),
            ))
        except (AttributeError, TypeError, ValueError, argparse.ArgumentTypeError) as error:
            raise ValueError(f"некорректная запись №{number} в хранилище") from error
    return expenses


def write_expenses(path: Path, expenses: list[Expense]) -> None:
    temp_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump([asdict(expense) for expense in expenses], temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
        temp_path.replace(path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def add_expense(path: Path, expense: Expense) -> None:
    # Блокировка остаётся действительной после атомарной замены JSON-файла.
    with path.with_name(path.name + ".lock").open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file, fcntl.LOCK_EX)

        expenses = read_expenses(path)
        expenses.append(expense)
        write_expenses(path, expenses)


def format_amount(kopecks: int) -> str:
    rubles, remainder = divmod(kopecks, 100)
    return f"{rubles},{remainder:02d} BYN"


def print_expenses(expenses: list[Expense]) -> None:
    if not expenses:
        print("Расходов нет.")
        return
    for expense in sorted(expenses, key=lambda item: item.date, reverse=True):
        note = f" | {expense.note}" if expense.note else ""
        print(f"{expense.date} | {expense.category} | {format_amount(expense.amount_kopecks)}{note}")


def print_summary(expenses: list[Expense], month: str) -> None:
    totals = defaultdict(int)
    for expense in expenses:
        totals[expense.category] += expense.amount_kopecks

    print(f"Расходы за {month}")
    for category, amount in sorted(totals.items(), key=lambda pair: (-pair[1], pair[0])):
        print(f"{category} | {format_amount(amount)}")
    print(f"Всего | {format_amount(sum(totals.values()))}")


def main() -> int:
    today = date.today().isoformat()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="путь к JSON-файлу")
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="добавить расход")
    add.add_argument("amount", type=parse_amount, help="сумма в BYN")
    add.add_argument("category", type=parse_category, help="категория расхода")
    add.add_argument("--date", type=parse_date, default=today, help="дата расхода, ГГГГ-ММ-ДД")
    add.add_argument("--note", type=parse_note, default="", help="комментарий")

    listing = commands.add_parser("list", help="показать расходы")
    listing.add_argument("--month", type=parse_month, help="фильтр по месяцу, ГГГГ-ММ")
    listing.add_argument("--category", type=parse_category, help="фильтр по категории")

    summary = commands.add_parser("summary", help="показать итог за месяц")
    summary.add_argument("month", type=parse_month, nargs="?", default=today[:7], help="месяц, ГГГГ-ММ")

    args = parser.parse_args()
    try:
        if args.command == "add":
            expense = Expense(args.date, args.category, args.amount, args.note)
            add_expense(args.file, expense)
            print(f"Добавлено | {format_amount(args.amount)} | {args.category} | {args.date}")
            return 0

        expenses = read_expenses(args.file)
        if args.month:
            expenses = [expense for expense in expenses if expense.date[:7] == args.month]
        if args.command == "summary":
            print_summary(expenses, args.month)
        else:
            if args.category:
                expenses = [expense for expense in expenses if expense.category == args.category]
            print_expenses(expenses)
    except (OSError, ValueError) as error:
        print(f"Ошибка при работе с файлом {args.file}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
