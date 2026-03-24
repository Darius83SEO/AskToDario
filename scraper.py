"""
PAA Scraper - Playwright-based Google PAA extraction
Usa Playwright con stealth per evitare blocchi Google.
Ogni richiesta apre un browser, scrapa e chiude (leggero per multi-utente).
"""

import os
import time
import random
import re
import subprocess
import streamlit as st
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

# === Installazione browser Chromium (una volta sola) ===
@st.cache_resource
def install_browser():
    """Installa Chromium per Playwright (eseguito una sola volta)"""
    subprocess.run(
        ["playwright", "install", "chromium"],
        check=True, capture_output=True
    )
    return True

# === Configurazione lingue e paesi ===
LANGUAGES = {
    'Italiano': 'it', 'English': 'en', 'Espanol': 'es', 'Francais': 'fr',
    'Deutsch': 'de', 'Portugues': 'pt', 'Nederlands': 'nl', 'Polski': 'pl',
    'Svenska': 'sv', 'Norsk': 'no', 'Dansk': 'da', 'Suomi': 'fi',
    'Cestina': 'cs', 'Magyar': 'hu', 'Romana': 'ro', 'Turkce': 'tr',
    'Japanese': 'ja', 'Korean': 'ko',
}

COUNTRIES = {
    'Italia': ('it', 'google.it'), 'United States': ('us', 'google.com'),
    'United Kingdom': ('uk', 'google.co.uk'), 'Espana': ('es', 'google.es'),
    'France': ('fr', 'google.fr'), 'Deutschland': ('de', 'google.de'),
    'Portugal': ('pt', 'google.pt'), 'Brasil': ('br', 'google.com.br'),
    'Nederland': ('nl', 'google.nl'), 'Polska': ('pl', 'google.pl'),
    'Sverige': ('se', 'google.se'), 'Norge': ('no', 'google.no'),
    'Danmark': ('dk', 'google.dk'), 'Suomi': ('fi', 'google.fi'),
    'Schweiz': ('ch', 'google.ch'), 'Osterreich': ('at', 'google.at'),
    'Turkiye': ('tr', 'google.com.tr'), 'Japan': ('jp', 'google.co.jp'),
    'India': ('in', 'google.co.in'), 'Australia': ('au', 'google.com.au'),
    'Canada': ('ca', 'google.ca'), 'Mexico': ('mx', 'google.com.mx'),
}

# Colori per i rami
BRANCH_COLORS = [
    '#4285F4', '#EA4335', '#FBBC05', '#34A853',
    '#FF6D01', '#46BDC6', '#9334E6', '#E91E63',
]

# JS per estrarre i 4 PAA iniziali
EXTRACT_PAA_JS = """
() => {
    var questions = [];
    var seen = new Set();
    function isNoise(text) {
        var lower = text.toLowerCase();
        var noise = ['cookie','privacy','feedback','impostazioni','accedi',
            'cerca con google','segnala','le persone hanno chiesto anche',
            'people also ask','altre domande','nutzer fragen auch',
            'autres questions posees','la gente tambien pregunta',
            'ingredienti','procedimento','classifica','top 10',
            'consigli per','in breve','gusti di pizza'];
        for (var i = 0; i < noise.length; i++) { if (lower.includes(noise[i])) return true; }
        if (text.length < 15 || text.split(' ').length < 3) return true;
        return false;
    }
    function addQ(text) {
        text = text.trim();
        if (text && !seen.has(text) && !isNoise(text) && text.length < 200) {
            seen.add(text); questions.push(text);
        }
    }
    var paaContainer = null;
    var allEls = document.querySelectorAll('div, span, h2, h3');
    for (var i = 0; i < allEls.length; i++) {
        var txt = allEls[i].textContent.trim();
        if (txt === 'Le persone hanno chiesto anche' || txt === 'People also ask' ||
            txt === 'Nutzer fragen auch' || txt === 'Autres questions posees' ||
            txt === 'La gente tambien pregunta' || txt === 'Altre domande' ||
            txt === 'Andre sporger ogsa' || txt === 'Folk fragar ocksa') {
            paaContainer = allEls[i];
            for (var j = 0; j < 10; j++) {
                if (!paaContainer.parentElement) break;
                paaContainer = paaContainer.parentElement;
                var items = paaContainer.querySelectorAll('[aria-expanded]');
                if (items.length >= 4) break;
            }
            break;
        }
    }
    if (paaContainer) {
        var allItems = paaContainer.querySelectorAll('[aria-expanded]');
        for (var k = 0; k < allItems.length && questions.length < 4; k++) {
            addQ(allItems[k].textContent.trim().split('\\n')[0].trim());
        }
    }
    if (questions.length === 0) {
        document.querySelectorAll('[data-sgrd="true"]').forEach(function(el) {
            if (questions.length < 4) addQ(el.textContent.trim().split('\\n')[0].trim());
        });
    }
    if (questions.length === 0) {
        document.querySelectorAll('div[jsname="Cpkphb"]').forEach(function(el) {
            if (questions.length >= 4) return;
            var spans = el.querySelectorAll('span');
            for (var s = 0; s < spans.length; s++) {
                if (spans[s].textContent.trim().length > 15) { addQ(spans[s].textContent.trim()); break; }
            }
        });
    }
    if (questions.length === 0) {
        document.querySelectorAll('.related-question-pair').forEach(function(el) {
            if (questions.length < 4) addQ(el.textContent.trim().split('\\n')[0].trim());
        });
    }
    if (questions.length === 0) {
        document.querySelectorAll('[data-q]').forEach(function(el) {
            if (questions.length < 4) addQ(el.getAttribute('data-q'));
        });
    }
    return questions;
}
"""


def _handle_consent(page):
    """Gestisce cookie consent di Google"""
    try:
        # Prova bottoni diretti
        for sel in ['button#L2AGLb', 'button#W0wltc', 'button[jsname="higCR"]',
                     'button[jsname="b3VHJd"]']:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(1500)
                return
        # Prova in iframe
        for frame in page.frames:
            for sel in ['button#L2AGLb', 'button#W0wltc', 'button[jsname="higCR"]']:
                try:
                    btn = frame.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(1500)
                        return
                except:
                    continue
        # Prova per testo
        for btn in page.query_selector_all('button'):
            try:
                txt = btn.inner_text().strip().lower()
                if any(kw in txt for kw in ['accetta', 'accept', 'agree']):
                    btn.click()
                    page.wait_for_timeout(1500)
                    return
            except:
                continue
    except:
        pass


def scrape_paa_single(query, hl='it', gl='it', google_domain='google.it'):
    """
    Scrapa i 4 PAA per una singola query.
    Apre browser -> scrapa -> chiude. Leggero per multi-utente.
    """
    questions = []
    url = f"https://www.{google_domain}/search?q={query}&hl={hl}&gl={gl}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-blink-features=AutomationControlled',
                ]
            )
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                locale=hl,
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/131.0.0.0 Safari/537.36'
                ),
            )
            page = context.new_page()
            stealth_sync(page)

            # Prima visita per consent
            page.goto(f"https://www.{google_domain}/", wait_until='domcontentloaded', timeout=15000)
            page.wait_for_timeout(2000)
            _handle_consent(page)

            # Ricerca vera
            page.goto(url, wait_until='domcontentloaded', timeout=15000)
            page.wait_for_timeout(random.randint(2000, 3500))

            # Check blocco
            if 'sorry' in page.url.lower():
                browser.close()
                return []

            # Scrolla per caricare PAA
            page.evaluate("window.scrollTo(0, 400)")
            page.wait_for_timeout(1000)

            # Estrai PAA
            questions = page.evaluate(EXTRACT_PAA_JS)

            if not questions:
                page.evaluate("window.scrollTo(0, 800)")
                page.wait_for_timeout(1500)
                questions = page.evaluate(EXTRACT_PAA_JS)

            browser.close()

    except Exception as e:
        st.warning(f"Errore scraping: {str(e)[:100]}")

    return questions or []


@st.cache_data(ttl=3600, show_spinner=False)
def get_paa_cached(query, hl, gl, google_domain):
    """Versione cachata - stessa query non viene ri-scrapata per 1 ora"""
    return scrape_paa_single(query, hl, gl, google_domain)


def extract_paa_tree(root_query, hl='it', gl='it', google_domain='google.it',
                     depth=3, progress_callback=None):
    """
    Estrazione ad albero completa: 4 PAA x livello, ricorsiva.
    Ritorna: (all_questions, edges, question_branches)
    - all_questions: list of (text, level, parent, branch_idx)
    - edges: list of (parent, child)
    - question_branches: dict question -> branch_index
    """
    all_questions = [(root_query, 0, None, -1)]
    edges = []
    question_branches = {root_query: -1}
    seen = {root_query}
    request_count = 0
    total_requests = sum(4**i for i in range(1, depth + 1))

    def fetch_recursive(question, current_depth, branch_idx):
        nonlocal request_count
        if current_depth >= depth:
            return

        # Delay tra richieste
        if request_count > 0:
            time.sleep(random.uniform(1.5, 2.5))

        request_count += 1
        if progress_callback:
            progress_callback(request_count, total_requests, question)

        related = get_paa_cached(question, hl, gl, google_domain)

        for rq in related:
            if rq in seen:
                continue
            seen.add(rq)
            question_branches[rq] = branch_idx
            all_questions.append((rq, current_depth + 1, question, branch_idx))
            edges.append((question, rq))
            fetch_recursive(rq, current_depth + 1, branch_idx)

    # Primo livello
    initial = get_paa_cached(root_query, hl, gl, google_domain)
    request_count += 1
    if progress_callback:
        progress_callback(1, total_requests, root_query)

    for i, q in enumerate(initial):
        if q in seen:
            continue
        seen.add(q)
        question_branches[q] = i
        all_questions.append((q, 1, root_query, i))
        edges.append((root_query, q))
        fetch_recursive(q, 1, i)

    return all_questions, edges, question_branches
