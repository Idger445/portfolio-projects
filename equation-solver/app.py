"""Local HTTP app for solving linear and quadratic equations."""

import argparse
from decimal import Decimal, localcontext
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re


PUBLIC_DIR = Path(__file__).resolve().with_name("dist")
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/examples": ("examples.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/plot.js": ("plot.js", "text/javascript; charset=utf-8"),
}
MAX_LENGTH = 160
NUMBER = r"(?:[0-9]{1,7}(?:[.,][0-9]{1,6})?|[.,][0-9]{1,6})"
TERM = re.compile(
    rf"\s*(?P<sign>[+-]?)\s*"
    rf"(?:(?:(?P<factor>{NUMBER})\s*(?:\*\s*)?)?x"
    rf"(?:\s*\^\s*(?P<power>[012]))?|(?P<constant>{NUMBER}))\s*",
    re.IGNORECASE | re.ASCII,
)
NORMALIZE = str.maketrans({"−": "-", "²": "^2", "¹": "^1", "⁰": "^0"})


def read_polynomial(side):
    """Read signed monomials in any order."""
    coefficients = [Decimal(0), Decimal(0), Decimal(0)]
    position = 0
    while position < len(side):
        term = TERM.match(side, position)
        if term is None or (position > 0 and not term["sign"]):
            raise ValueError("Используйте числа и степени x до второй, например 2x^2 − 3x + 1.")
        degree = 0 if term["constant"] else int(term["power"] or 1)
        amount = Decimal((term["constant"] or term["factor"] or "1").replace(",", "."))
        coefficients[2 - degree] += -amount if term["sign"] == "-" else amount
        position = term.end()
    return coefficients


def describe(value):
    if not value:
        return "0"
    if Decimal("0.000001") <= abs(value) < Decimal("1e9"):
        return format(Decimal(format(value, ".11g")).normalize(), "f").replace("-", "−")
    mantissa, exponent = format(value.normalize(), ".10e").split("e")
    return f"{mantissa.rstrip('0').rstrip('.').replace('-', '−')}e{int(exponent)}"


def describe_polynomial(a, b, c):
    terms = []
    for value, variable in ((a, "x²"), (b, "x"), (c, "")):
        if not value:
            continue
        magnitude = "" if variable and abs(value) == 1 else describe(abs(value))
        sign = (" − " if value < 0 else " + ") if terms else ("−" if value < 0 else "")
        terms.append(f"{sign}{magnitude}{variable}")
    return "".join(terms) or "0"


def solve(equation):
    """Return the solution and numeric data for graphing the residual."""
    if not isinstance(equation, str) or not 1 <= len(equation) <= MAX_LENGTH:
        raise ValueError(f"Введите уравнение длиной до {MAX_LENGTH} символов.")
    left, separator, right = equation.translate(NORMALIZE).partition("=")
    if not separator or not left.strip() or not right.strip() or "=" in right:
        raise ValueError("Укажите обе части уравнения через один знак =.")

    with localcontext() as context:
        context.prec = 40
        a, b, c = (
            left_value - right_value
            for left_value, right_value in zip(read_polynomial(left), read_polynomial(right))
        )
        roots = []
        discriminant = None
        if a:
            discriminant = b * b - 4 * a * c
            if discriminant < 0:
                real = -b / (2 * a)
                imaginary = (-discriminant).sqrt() / abs(2 * a)
                imaginary_term = "i" if imaginary == 1 else f"{describe(imaginary)}i"
                result = f"x = {describe(real)} ± {imaginary_term}" if real else f"x = ±{imaginary_term}"
                kind = "Два комплексных корня"
            elif discriminant == 0:
                roots = [-b / (2 * a)]
                result = f"x = {describe(roots[0])}"
                kind = "Один действительный корень"
            else:
                # Avoid subtracting similar values in one branch of the quadratic formula.
                q = -(b + discriminant.sqrt().copy_sign(b)) / 2
                roots = sorted([q / a, c / q])
                result = f"x₁ = {describe(roots[0])}, x₂ = {describe(roots[1])}"
                kind = "Два действительных корня"
        elif b:
            roots = [-c / b]
            result = f"x = {describe(roots[0])}"
            kind = "Один действительный корень"
        else:
            kind = "Тождество" if c == 0 else "Решений нет"
            result = "Любое x" if c == 0 else "∅"

        vertex = -b / (2 * a) if a else None
        return {
            "kind": kind,
            "result": result,
            "discriminant": describe(discriminant) if discriminant is not None else None,
            "expression": describe_polynomial(a, b, c),
            "coefficients": [float(a), float(b), float(c)],
            "roots": [{"x": float(root), "label": describe(root)} for root in roots],
            "vertex": float(vertex) if vertex is not None else None,
        }


class Handler(BaseHTTPRequestHandler):
    def send_body(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, result):
        body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_body(status, "application/json; charset=utf-8", body)

    def do_GET(self):
        asset = ASSETS.get(self.path.partition("?")[0])
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        name, content_type = asset
        self.send_body(HTTPStatus.OK, content_type, (PUBLIC_DIR / name).read_bytes())

    def do_POST(self):
        if self.path != "/api/solve":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Маршрут не найден."})
            return
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Отправьте уравнение в формате JSON.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2048:
                raise ValueError("Недопустимый размер запроса.")
            try:
                payload = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeError) as error:
                raise ValueError("Не удалось прочитать JSON.") from error
            if not isinstance(payload, dict):
                raise ValueError("Укажите поле equation в объекте JSON.")
            result = solve(payload.get("equation"))
        except ValueError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self.send_json(HTTPStatus.OK, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001, help="HTTP port, default 8001")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("the port must be between 0 and 65535")

    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Откройте http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
