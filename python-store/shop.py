"""Локальная демонстрационная витрина канцелярских товаров."""

from argparse import ArgumentParser
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4


ROOT = Path(__file__).resolve().parent
LIMIT = 12


@dataclass(frozen=True)
class Product:
    name: str
    details: str
    price: int
    variant: str
    description: str
    specifications: tuple[tuple[str, str], ...]


CATALOG = {
    "notebook": Product(
        "Блокнот «Мох»", "A5 · 160 страниц в точку", 3400, "Мох",
        "Блокнот в зелёной тканевой обложке для заметок, схем и набросков. "
        "Точечная разметка помогает выравнивать строки и строить таблицы.",
        (("Формат", "A5 (148 × 210 мм)"), ("Разметка", "Точка"), ("Объём", "160 страниц")),
    ),
    "planner": Product(
        "Планер «Лён»", "A5 · 52 недели без дат", 4200, "Лён",
        "На каждом развороте есть место для дел на неделю и отдельный блок для заметок. "
        "Даты можно проставлять по ходу работы и начинать с любой недели года.",
        (("Формат", "A5 (148 × 210 мм)"), ("Развороты", "52 недели"), ("Обложка", "Тканевая, бежевая")),
    ),
    "pencil": Product(
        "Карандаш «Графит»", "Грифель HB · кедр", 650, "Графит",
        "Кедровый карандаш с шестигранным корпусом и грифелем средней твёрдости. "
        "Подходит для повседневных записей и лёгких набросков.",
        (("Твёрдость", "HB"), ("Корпус", "Шестигранный, кедр"), ("Комплектация", "1 карандаш")),
    ),
}


def money(kopecks):
    return f"{kopecks // 100},{kopecks % 100:02d} BYN"


def totals(cart):
    return sum(CATALOG[sku].price * quantity for sku, quantity in cart.items())


def init_db(path):
    with closing(sqlite3.connect(path)) as database, database:
        database.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                checkout_token TEXT NOT NULL UNIQUE,
                customer TEXT NOT NULL,
                email TEXT NOT NULL,
                total_kopecks INTEGER NOT NULL,
                ordered_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_items (
                order_id INTEGER NOT NULL REFERENCES orders(id),
                sku TEXT NOT NULL,
                name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_kopecks INTEGER NOT NULL,
                PRIMARY KEY (order_id, sku)
            );
        """)


def save_order(path, token, customer, email, cart):
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("PRAGMA foreign_keys = ON")
        database.execute("BEGIN IMMEDIATE")
        previous = database.execute(
            "SELECT id FROM orders WHERE checkout_token = ?", (token,)
        ).fetchone()
        if previous:
            return previous[0]

        order = database.execute(
            "INSERT INTO orders (checkout_token, customer, email, total_kopecks, ordered_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (token, customer, email, totals(cart), datetime.now(timezone.utc).isoformat()),
        )
        order_id = order.lastrowid
        database.executemany(
            "INSERT INTO order_items (order_id, sku, name, quantity, unit_kopecks)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                (order_id, sku, CATALOG[sku].name, quantity, CATALOG[sku].price)
                for sku, quantity in cart.items()
            ),
        )
        return order_id


def layout(title, content, count, current=""):
    home_current = ' aria-current="page"' if current == "home" else ""
    catalog_current = {"catalog": ' aria-current="page"', "product": ' aria-current="location"'}.get(current, "")
    cart_current = ' aria-current="page"' if current == "cart" else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Блокноты, планеры и карандаши в магазине Поле.">
  <title>{escape(title)} — Поле</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <a class="skip-link" href="#page-content">К содержимому</a>
  <header class="site-header wrap">
    <a class="brand" aria-label="Поле, главная" href="/"{home_current}>поле<span>.</span></a>
    <nav aria-label="Основная навигация">
      <a href="/catalog"{catalog_current}>Каталог</a>
      <a class="cart-link" href="/cart"{cart_current}>Корзина <span class="count">{count}</span></a>
    </nav>
  </header>
  <main id="page-content" class="wrap">{content}</main>
  <footer class="site-footer wrap"><a class="brand" aria-label="Поле, главная" href="/">поле<span>.</span></a><p>Демонстрационный магазин канцтоваров</p></footer>
</body>
</html>"""


def home_page():
    return f"""<section class="hero" aria-labelledby="intro">
      <div class="hero-copy">
        <p class="variant">Бумага и канцелярия</p>
        <h1 id="intro">Место для идей</h1>
        <p>Блокноты, планеры и карандаши для повседневных записей.</p>
        <a class="button primary" href="/catalog">Смотреть каталог <span aria-hidden="true">→</span></a>
      </div>
      <img src="/static/collection.png" alt="Зелёный и светлый блокноты с карандашом на столе" width="1536" height="1024">
    </section>
    <section id="catalog" class="home-collection" aria-labelledby="collection-title">
      <h2 id="collection-title">Выбрать по задаче</h2>
      <ul class="quick-links">
        <li><a href="/products/notebook">Для заметок <span>{CATALOG["notebook"].name}</span></a></li>
        <li><a href="/products/planner">Для планов <span>{CATALOG["planner"].name}</span></a></li>
        <li><a href="/products/pencil">Для набросков <span>{CATALOG["pencil"].name}</span></a></li>
      </ul>
    </section>"""


def add_button(sku, cart, source):
    style = "primary" if source == "product" else "secondary"
    if cart.get(sku, 0) >= LIMIT:
        return f'<a class="button {style}" href="/cart">Перейти в корзину</a>'
    return f"""<form action="/cart/add" method="post">
      <input type="hidden" name="sku" value="{sku}">
      <input type="hidden" name="source" value="{source}">
      <button class="button {style}" aria-label="В корзину — {CATALOG[sku].name}">В корзину</button>
    </form>"""


def cart_notice(added, cart):
    if added in cart:
        return f'<p class="notice" role="status">{CATALOG[added].name} · в корзине {cart[added]} шт.</p>'
    return ""


def product_art(sku):
    return f'<div class="product-art {sku}" aria-hidden="true"><span></span></div>'


def catalog_page(cart, added):
    cards = []
    for sku, product in CATALOG.items():
        cards.append(f"""<article class="product">
          <a class="product-link" href="/products/{sku}">
            {product_art(sku)}
            <p class="variant">{product.variant}</p>
            <h2>{product.name}</h2>
          </a>
          <p class="details">{product.details}</p>
          <div class="product-actions"><strong>{money(product.price)}</strong>{add_button(sku, cart, "catalog")}</div>
        </article>""")
    return f"""<section class="catalog" aria-labelledby="catalog-title">
      <h1 id="catalog-title">Каталог</h1>
      {cart_notice(added, cart)}
      <div class="products">{"".join(cards)}</div>
    </section>"""


def product_page(sku, cart, added):
    product = CATALOG[sku]
    specifications = "".join(
        f"<div><dt>{label}</dt><dd>{value}</dd></div>" for label, value in product.specifications
    )
    return f"""<a class="back-link" href="/catalog">← К каталогу</a>
    <article class="product-detail">
      {product_art(sku)}
      <div>
        <h1>{product.name}</h1>
        <p class="product-description">{product.description}</p>
        <dl class="specifications">{specifications}</dl>
        <div class="product-actions"><strong>{money(product.price)}</strong>{add_button(sku, cart, "product")}</div>
        {cart_notice(added, cart) if added == sku else ""}
      </div>
    </article>"""


def cart_page(cart, checkout_token, error="", customer="", email=""):
    status = f'<p class="notice error" role="alert">{escape(error)}</p>' if error else ""
    heading = f'<a class="back-link" href="/catalog">← К каталогу</a><h1>Корзина</h1>{status}'
    if not cart:
        return heading + '<div class="panel"><p>Корзина пока пуста.</p><a class="button primary" href="/catalog">К покупкам</a></div>'

    items = []
    for sku, quantity in cart.items():
        product = CATALOG[sku]
        items.append(f"""<li class="cart-item">
          <div><h2><a href="/products/{sku}">{product.name}</a></h2><p class="details">{money(product.price)} за шт.</p></div>
          <strong>{money(product.price * quantity)}</strong>
          <form method="post" action="/cart/update" class="quantity-form">
            <input type="hidden" name="sku" value="{sku}">
            <label for="qty-{sku}">Количество</label>
            <input type="number" id="qty-{sku}" name="quantity" min="1" max="{LIMIT}" value="{quantity}" required>
            <button class="button secondary">Обновить</button>
          </form>
          <form method="post" action="/cart/update" class="remove-form">
            <input type="hidden" name="sku" value="{sku}">
            <input type="hidden" name="quantity" value="0">
            <button class="text-button" aria-label="Убрать — {product.name}">Убрать</button>
          </form>
        </li>""")
    return heading + f"""<div class="cart-grid">
      <ul class="cart-items">{"".join(items)}</ul>
      <section class="panel checkout" aria-labelledby="checkout-title">
        <h2 id="checkout-title">Оформление заказа</h2>
        <div class="total"><span>Итого</span><strong>{money(totals(cart))}</strong></div>
        <form method="post" action="/checkout">
          <input type="hidden" name="token" value="{checkout_token}">
          <label for="customer">Имя</label>
          <input name="customer" id="customer" autocomplete="name" value="{escape(customer, quote=True)}" maxlength="80" required>
          <label for="email">Электронная почта</label>
          <input name="email" id="email" type="email" autocomplete="email" value="{escape(email, quote=True)}" maxlength="254" required>
          <button class="button primary">Оформить демозаказ</button>
        </form>
        <p class="details">Заказ сохранится в демонстрационной базе. Оплата и доставка не выполняются.</p>
      </section>
    </div>"""


class ShopHandler(BaseHTTPRequestHandler):
    def read_cookie(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            cookies.clear()
        return cookies

    def cart(self):
        stored = self.read_cookie().get("shop_cart")
        cart = {}
        if stored:
            for item in stored.value.split("|"):
                sku, _, quantity = item.partition(":")
                if sku in CATALOG and re.fullmatch(r"[0-9]{1,2}", quantity):
                    count = int(quantity)
                    if 1 <= count <= LIMIT:
                        cart[sku] = count
        return cart

    def respond(self, status, content_type, body=b"", headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def page(self, title, content, cart, status=HTTPStatus.OK, headers=(), *, current=""):
        body = layout(title, content, sum(cart.values()), current).encode()
        self.respond(status, "text/html; charset=utf-8", body, headers)

    def show_cart(self, cart, error="", customer="", email=""):
        token = uuid4().hex
        cookie = f"shop_checkout={token}; Path=/; HttpOnly; SameSite=Strict"
        status = HTTPStatus.BAD_REQUEST if error else HTTPStatus.OK
        self.page(
            "Корзина", cart_page(cart, token, error, customer, email), cart, status,
            (("Set-Cookie", cookie),), current="cart",
        )

    def redirect(self, location, cart):
        value = "|".join(f"{sku}:{quantity}" for sku, quantity in cart.items())
        cookie = f"shop_cart={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={604800 if cart else 0}"
        self.respond(HTTPStatus.SEE_OTHER, "text/plain", headers=(("Location", location), ("Set-Cookie", cookie)))

    def do_GET(self):
        url = urlsplit(self.path)
        assets = {
            "/static/style.css": ("style.css", "text/css; charset=utf-8"),
            "/static/collection.png": ("collection.png", "image/png"),
        }
        if url.path in assets:
            filename, content_type = assets[url.path]
            self.respond(HTTPStatus.OK, content_type, (ROOT / "static" / filename).read_bytes())
            return

        cart = self.cart()
        added = parse_qs(url.query).get("added", [""])[0]
        if url.path == "/":
            if added in CATALOG:
                self.respond(HTTPStatus.FOUND, "text/plain", headers=(("Location", f"/catalog?added={added}"),))
                return
            self.page("Канцелярия", home_page(), cart, current="home")
        elif url.path == "/catalog":
            self.page("Каталог", catalog_page(cart, added), cart, current="catalog")
        elif url.path == "/cart":
            self.show_cart(cart)
        elif url.path.startswith("/products/") and (sku := url.path.removeprefix("/products/")) in CATALOG:
            self.page(CATALOG[sku].name, product_page(sku, cart, added), cart, current="product")
        else:
            self.page("Страница не найдена", '<h1>Страница не найдена</h1><a href="/">На главную</a>', cart, HTTPStatus.NOT_FOUND)

    def read_form(self):
        origin = self.headers.get("Origin")
        if origin and (
            urlsplit(origin).scheme != "http"
            or urlsplit(origin).netloc != self.headers.get("Host")
        ):
            raise ValueError("Отправьте форму со страницы магазина.")
        if self.headers.get_content_type() != "application/x-www-form-urlencoded":
            raise ValueError("Ожидалась форма магазина.")
        size = self.headers.get("Content-Length", "")
        if not re.fullmatch(r"[0-9]{1,5}", size) or not 1 <= int(size) <= 8192:
            raise ValueError("Некорректный размер формы.")
        return {
            key: values[-1] for key, values in parse_qs(
                self.rfile.read(int(size)).decode("utf-8"),
                encoding="utf-8", errors="strict", max_num_fields=12,
            ).items()
        }

    def do_POST(self):
        path = urlsplit(self.path).path
        cart = self.cart()
        if path not in {"/cart/add", "/cart/update", "/checkout"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            form = self.read_form()
        except ValueError:
            self.show_cart(cart, "Не удалось принять форму. Попробуйте ещё раз.")
            return
        if path == "/checkout":
            self.checkout(cart, form)
            return

        sku = form.get("sku")
        if sku not in CATALOG:
            self.show_cart(cart, "Товар отсутствует в каталоге.")
        elif path == "/cart/add":
            cart[sku] = min(cart.get(sku, 0) + 1, LIMIT)
            location = f"/products/{sku}" if form.get("source") == "product" else "/catalog"
            self.redirect(f"{location}?added={sku}", cart)
        else:
            quantity = form.get("quantity", "")
            if sku not in cart or not re.fullmatch(r"[0-9]{1,2}", quantity) or int(quantity) > LIMIT:
                self.show_cart(cart, f"Допустимое количество — от 1 до {LIMIT}.")
                return
            if int(quantity):
                cart[sku] = int(quantity)
            else:
                del cart[sku]
            self.redirect("/cart", cart)

    def checkout(self, cart, form):
        customer = form.get("customer", "").strip()
        email = form.get("email", "").strip()
        token = form.get("token", "")
        stored = self.read_cookie().get("shop_checkout")
        if not cart:
            self.show_cart(cart, "Добавьте товары перед оформлением.")
            return
        if not stored or not re.fullmatch(r"[0-9a-f]{32}", token) or stored.value != token:
            self.show_cart(cart, "Форма устарела. Проверьте корзину и повторите отправку.", customer, email)
            return
        if not customer or len(customer) > 80 or not customer.isprintable():
            self.show_cart(cart, "Введите имя длиной до 80 символов.", customer, email)
            return
        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or not email.isprintable():
            self.show_cart(cart, "Проверьте адрес электронной почты.", customer, email)
            return
        try:
            order_id = save_order(self.server.database_path, token, customer, email, cart)
        except sqlite3.Error as error:
            self.log_error("Order database error: %s", error)
            self.show_cart(cart, "Сохранить заказ сейчас не удалось.", customer, email)
            return
        cookie = 'shop_cart=""; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'
        self.page(
            "Заказ оформлен",
            f'<section class="panel confirmation"><h1>Заказ №{order_id} оформлен</h1>'
            '<p>Демонстрационный заказ сохранён.</p><a class="button primary" href="/catalog">Вернуться в каталог</a></section>',
            {}, HTTPStatus.CREATED, (("Set-Cookie", cookie),),
        )


def serve(port, database_path):
    init_db(database_path)
    with ThreadingHTTPServer(("127.0.0.1", port), ShopHandler) as server:
        server.database_path = database_path
        print(f"Магазин запущен на http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000, help="локальный порт (по умолчанию 8000)")
    parser.add_argument("--db", type=Path, default=ROOT / "shop.sqlite3", help="путь к файлу SQLite")
    arguments = parser.parse_args()
    if not 0 <= arguments.port <= 65535:
        parser.error("порт должен быть между 0 и 65535")
    try:
        serve(arguments.port, arguments.db)
    except (OSError, sqlite3.Error) as error:
        parser.exit(1, f"Ошибка запуска: {error}\n")
