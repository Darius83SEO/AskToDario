"""
PAA Scraper - curl_cffi based (no browser needed)
Usa curl_cffi per impersonare Chrome a livello TLS.
Molto piu' veloce e leggero di Playwright, funziona su Streamlit Cloud.
"""

import time
import random
import re
import streamlit as st
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
import json

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

BRANCH_COLORS = [
    '#4285F4', '#EA4335', '#FBBC05', '#34A853',
    '#FF6D01', '#46BDC6', '#9334E6', '#E91E63',
]

# PAA heading texts per lingua
PAA_HEADINGS = [
    'le persone hanno chiesto anche',
    'people also ask',
    'nutzer fragen auch',
    'autres questions posees',
    'otras preguntas de los usuarios',
    'la gente tambien pregunta',
    'altre domande',
    'andre sporger ogsa',
    'folk fragar ocksa',
    'os utilizadores tambem perguntam',
    'pessoas tambem perguntam',
]


def extract_paa_from_html(html_text):
    """
    Estrae PAA dal codice HTML grezzo di Google.
    Usa strategie multiple perche' Google cambia spesso la struttura.
    """
    soup = BeautifulSoup(html_text, 'html.parser')
    questions = []
    seen = set()

    def add_q(text):
        text = text.strip()
        if not text or len(text) < 15 or len(text) > 250 or text in seen:
            return
        lower = text.lower()
        noise = ['cookie', 'privacy', 'feedback', 'impostazioni', 'accedi',
                 'cerca con google', 'segnala', 'google', 'classifica',
                 'top 10', 'ingredienti', 'procedimento', 'consigli per']
        if any(n in lower for n in noise):
            return
        if text.split(' ').__len__() < 3:
            return
        seen.add(text)
        questions.append(text)

    # --- Strategia 1: Trova sezione PAA tramite heading e prendi i div fratelli ---
    for heading_text in PAA_HEADINGS:
        # Cerca in span, div, h2, h3
        for tag in soup.find_all(string=re.compile(re.escape(heading_text), re.I)):
            container = tag.find_parent('div')
            if not container:
                continue
            # Risali fino a trovare il contenitore con piu' elementi
            for _ in range(8):
                parent = container.find_parent('div')
                if not parent:
                    break
                expandables = parent.find_all(attrs={'aria-expanded': True})
                if len(expandables) >= 3:
                    container = parent
                    break
                container = parent

            # Estrai domande dagli elementi espandibili
            for el in container.find_all(attrs={'aria-expanded': True}):
                text = el.get_text(separator='\n').strip().split('\n')[0].strip()
                add_q(text)

            # Prova anche data-sgrd
            for el in container.find_all(attrs={'data-sgrd': 'true'}):
                text = el.get_text(separator='\n').strip().split('\n')[0].strip()
                add_q(text)

            if questions:
                return questions[:4]

    # --- Strategia 2: data-sgrd globale ---
    for el in soup.select('[data-sgrd="true"]'):
        text = el.get_text(separator='\n').strip().split('\n')[0].strip()
        add_q(text)
    if questions:
        return questions[:4]

    # --- Strategia 3: jsname Cpkphb ---
    for el in soup.select('div[jsname="Cpkphb"]'):
        for span in el.find_all('span'):
            text = span.get_text().strip()
            if len(text) > 15:
                add_q(text)
                break
    if questions:
        return questions[:4]

    # --- Strategia 4: related-question-pair legacy ---
    for el in soup.select('.related-question-pair'):
        text = el.get_text(separator='\n').strip().split('\n')[0].strip()
        add_q(text)
    if questions:
        return questions[:4]

    # --- Strategia 5: data-q attributo ---
    for el in soup.select('[data-q]'):
        add_q(el.get('data-q', ''))
    if questions:
        return questions[:4]

    # --- Strategia 6: Cerca nei tag <script> per dati JSON embedded ---
    for script in soup.find_all('script'):
        script_text = script.string or ''
        # Cerca pattern tipo ["domanda?", ...] nel JS
        matches = re.findall(r'"([^"]{20,150}\?)"', script_text)
        for m in matches:
            if any(h in m.lower() for h in PAA_HEADINGS):
                continue
            add_q(m)
        if len(questions) >= 4:
            return questions[:4]

    # --- Strategia 7: Cerca aria-expanded elements globali ---
    for el in soup.find_all(attrs={'aria-expanded': 'false'}):
        text = el.get_text(separator='\n').strip().split('\n')[0].strip()
        if len(text) > 15 and text.count(' ') >= 3:
            add_q(text)
    if questions:
        return questions[:4]

    return questions[:4]


def scrape_paa_single(query, hl='it', gl='it', google_domain='google.it'):
    """
    Scrapa i 4 PAA per una singola query usando curl_cffi.
    Impersona Chrome a livello TLS per non farsi bloccare.
    """
    url = f"https://www.{google_domain}/search?q={query}&hl={hl}&gl={gl}&num=10"

    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': f'{hl},{hl[:2]};q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': f'https://www.{google_domain}/',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    }

    try:
        response = curl_requests.get(
            url,
            headers=headers,
            impersonate="chrome",
            timeout=15,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return []

        if 'sorry' in response.url.lower() or '/sorry/' in response.text[:500].lower():
            return []

        return extract_paa_from_html(response.text)

    except Exception as e:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def get_paa_cached(query, hl, gl, google_domain):
    """Versione cachata — stessa query non viene ri-scrapata per 1 ora"""
    return scrape_paa_single(query, hl, gl, google_domain)


def extract_paa_tree(root_query, hl='it', gl='it', google_domain='google.it',
                     depth=3, progress_callback=None):
    """
    Estrazione ad albero: 4 PAA x livello, ricorsiva.
    Ritorna: (all_questions, edges, question_branches)
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
            time.sleep(random.uniform(0.8, 1.5))

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
