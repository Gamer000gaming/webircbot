import irc.bot
import requests
from bs4 import BeautifulSoup
import textwrap
import random
import time
import json
import os
from urllib.parse import urljoin
import threading

# --- Files for persistence ---
DATA_FILE = "webirc_data.json"

# --- In-memory state ---
user_pages = {}
user_keywords = {}
help_sent = {}
last_links = {}  # Stores per-user {"base": url, "links": [...]}

# --- Config ---
MAX_TEXT_LENGTH = 10000  # truncate huge pages
CHUNK_SIZE = 400
CHUNK_DELAY = 0.5  # seconds between messages

# --- Utilities ---
def save_data():
    data = {
        "pages": user_pages,
        "keywords": user_keywords,
        "help_sent": list(help_sent.keys())
    }
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_data():
    global user_pages, user_keywords, help_sent
    if not os.path.exists(DATA_FILE):
        return
    with open(DATA_FILE) as f:
        data = json.load(f)
    user_pages = data.get("pages", {})
    user_keywords = data.get("keywords", {})
    help_sent = {nick: True for nick in data.get("help_sent", [])}

def send_multiline(conn, target, lines):
    """Send each line in a separate thread-safe chunked manner."""
    def worker():
        for line in lines:
            conn.privmsg(target, line)
            time.sleep(CHUNK_DELAY)
    threading.Thread(target=worker, daemon=True).start()

def send_help(conn, nick):
    """Send help message line-by-line."""
    help_lines = [
        "? WebIRC Help:",
        "&edit <text> : Create or replace your personal page (max 400 chars).",
        "&view <nick> : View someone else's page.",
        "&keywords <word1> (<word2>...) : Set your keywords.",
        "&random : View a random page.",
        "&search <term> : Search pages by keyword.",
        "&help : Show this help message.",
        "Or send a URL (like example.com) to browse the web via DMs.",
        "Reply with a number to follow a link.",
    ]
    send_multiline(conn, nick, help_lines)

def chunk_text(text, width=CHUNK_SIZE):
    """Split text into word-wrapped chunks <= width characters."""
    return textwrap.wrap(text, width=width)

def fetch_page(url):
    """Fetch a page, retrying with HTTP if HTTPS fails."""
    if not url.startswith("http"):
        url = "https://" + url  # default to HTTPS

    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "WebIRC/1.0"})
        r.raise_for_status()
    except requests.exceptions.SSLError:
        # SSL error, try plain HTTP
        url = "http://" + url.split("://")[-1]
        try:
            r = requests.get(url, timeout=8, headers={"User-Agent": "WebIRC/1.0"})
            r.raise_for_status()
        except Exception as e:
            return f"Error fetching {url}: {e}", []
    except Exception as e:
        return f"Error fetching {url}: {e}", []

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = text[:MAX_TEXT_LENGTH]  # truncate very long pages
    links = [a.get("href") for a in soup.find_all("a", href=True)]
    return text, links[:10]

def send_page_chunks(conn, nick, text, links):
    """Send a page to a user in chunks with numbered links in a separate thread."""
    def worker():
        if len(text) >= MAX_TEXT_LENGTH:
            conn.privmsg(nick, f"?? Page too long, showing first {MAX_TEXT_LENGTH} chars only.")
        for chunk in chunk_text(text, CHUNK_SIZE):
            conn.privmsg(nick, chunk)
            time.sleep(CHUNK_DELAY)
        for i, link in enumerate(links):
            conn.privmsg(nick, f"[{i+1}] {link}")
    threading.Thread(target=worker, daemon=True).start()

# --- Bot ---
class WebIRCBot(irc.bot.SingleServerIRCBot):
    def __init__(self, server, port, nickname, channel=None):
        super().__init__([(server, port)], nickname, nickname)
        self.channel = channel
        load_data()
        print("WebIRC bot initialized")

    def on_welcome(self, connection, event):
        print("Connected to IRC server.")
        if self.channel:
            connection.join(self.channel)

    def on_privmsg(self, connection, event):
        nick = event.source.nick
        msg = event.arguments[0].strip()

        # First-time message
        if nick not in help_sent:
            help_sent[nick] = True
            save_data()
            send_help(connection, nick)
            return

        # Commands
        if msg.startswith("&edit "):
            text = msg[6:].strip()
            if len(text) > 400:
                connection.privmsg(nick, "Text too long (max 400 chars).")
            else:
                user_pages[nick] = text
                save_data()
                connection.privmsg(nick, "Page updated.")
            return

        if msg.startswith("&view "):
            target = msg[6:].strip()
            if target in user_pages:
                connection.privmsg(nick, f"{target}'s page: {user_pages[target]}")
            else:
                connection.privmsg(nick, "Page not found.")
            return

        if msg.startswith("&keywords "):
            words = msg[10:].split()
            user_keywords[nick] = words
            save_data()
            connection.privmsg(nick, f"Keywords updated: {', '.join(words)}")
            return

        if msg == "&random":
            if user_pages:
                target, page = random.choice(list(user_pages.items()))
                connection.privmsg(nick, f"Random page from {target}: {page}")
            else:
                connection.privmsg(nick, "No pages available yet.")
            return

        if msg.startswith("&search "):
            term = msg[8:].strip().lower()
            matches = [
                u for u, kw in user_keywords.items()
                if term in [w.lower() for w in kw]
            ]
            if matches:
                connection.privmsg(nick, "Matches: " + ", ".join(matches))
            else:
                connection.privmsg(nick, "No matches found.")
            return

        if msg == "&help":
            send_help(connection, nick)
            return

        # URLs
        if "." in msg and " " not in msg:
            connection.privmsg(nick, f"Fetching {msg}...")
            text, links = fetch_page(msg)
            send_page_chunks(connection, nick, text, links)
            last_links[nick] = {"base": msg if msg.startswith("http") else "https://" + msg, "links": links}
            return

        # Follow numbered links
        if msg.isdigit():
            if nick in last_links and last_links[nick]["links"]:
                idx = int(msg)-1
                if 0 <= idx < len(last_links[nick]["links"]):
                    base_url = last_links[nick]["base"]
                    raw_link = last_links[nick]["links"][idx]
                    url = urljoin(base_url, raw_link)  # resolves relative URLs
                    connection.privmsg(nick, f"? Fetching {url}...")
                    text, links = fetch_page(url)
                    send_page_chunks(connection, nick, text, links)
                    last_links[nick] = {"base": url, "links": links}
                else:
                    connection.privmsg(nick, "Invalid link number.")
            else:
                connection.privmsg(nick, "Send a URL first, then reply with a link number.")
            return

if __name__ == "__main__":
    bot = WebIRCBot("server", 6667, "nickname")
    bot.start()
