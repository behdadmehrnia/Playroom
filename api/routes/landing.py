"""Landing page for the Playroom API."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["Landing"])

LOGO_PATH = Path(__file__).resolve().parent.parent / "logo.svg"

LANDING_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#000000">
    <title>Playroom</title>
    <meta name="description" content="A safe AI companion for children — five modes, grounded in the school textbook.">
    <link rel="icon" type="image/svg+xml" href="/logo.svg">
    <style>
        :root {
            --bg: #000;
            --panel: #121212;
            --panel-soft: #181818;
            --panel-raised: #242424;
            --line: rgba(255, 255, 255, 0.08);
            --text: #fff;
            --muted: #b3b3b3;
            --quiet: #737373;
            --radius: 14px;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        html { -webkit-text-size-adjust: 100%; }

        body {
            background: var(--bg);
            color: var(--text);
            font-family: "Circular", "Avenir Next", "Helvetica Neue", -apple-system,
                         BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            font-size: 14px;
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
            padding: 8px;
        }

        .shell { max-width: 1180px; margin: 0 auto; }

        .panel {
            background: var(--panel);
            border-radius: var(--radius);
            padding: 40px;
        }

        .topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            padding: 18px 24px;
            background: var(--panel);
            border-radius: var(--radius);
            margin-bottom: 8px;
        }

        .brand {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            font-weight: 800;
            letter-spacing: -0.03em;
            font-size: 17px;
        }

        .brand svg { display: block; }

        .topnav { display: flex; align-items: center; gap: 4px; }

        .topnav a {
            color: var(--muted);
            text-decoration: none;
            font-weight: 700;
            font-size: 13px;
            padding: 8px 12px;
            border-radius: 2px;
            transition: color .15s ease, background .15s ease;
        }

        .topnav a:hover { color: var(--text); background: var(--panel-raised); }

        .overline {
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: var(--quiet);
        }

        .hero { padding: 56px 40px 48px; }

        .hero h1 {
            font-size: clamp(40px, 7vw, 68px);
            font-weight: 800;
            letter-spacing: -0.04em;
            line-height: 1.02;
            margin: 14px 0 0;
            max-width: 15ch;
        }

        .hero p.lede {
            color: var(--muted);
            font-size: 16px;
            max-width: 58ch;
            margin-top: 18px;
        }

        .cta-row { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 30px; }

        .btn-primary {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #fff;
            color: #000;
            font-weight: 800;
            font-size: 14px;
            letter-spacing: -0.01em;
            text-decoration: none;
            padding: 13px 26px;
            border-radius: 999px;
            transition: transform .15s ease;
        }

        .btn-primary:hover { transform: scale(1.04); }

        .btn-ghost {
            color: var(--muted);
            font-weight: 700;
            text-decoration: none;
            padding: 13px 16px;
            border-radius: 2px;
        }

        .btn-ghost:hover { color: var(--text); }

        section { margin-top: 8px; }

        .section-head { margin-bottom: 22px; }

        .section-head h2 {
            font-size: 26px;
            font-weight: 800;
            letter-spacing: -0.03em;
            margin-top: 10px;
        }

        .section-head p { color: var(--muted); margin-top: 6px; max-width: 62ch; }

        .modes {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 16px;
        }

        .mode { text-decoration: none; display: block; }

        .mode .tile {
            position: relative;
            aspect-ratio: 1 / 1;
            border-radius: 6px;
            overflow: hidden;
            display: flex;
            align-items: flex-end;
            padding: 14px;
            transition: transform .18s ease;
        }

        .mode:hover .tile { transform: translateY(-4px); }

        .mode .tile::after {
            content: "";
            position: absolute;
            inset: 0;
            background:
                radial-gradient(circle at 50% 46%, rgba(255,255,255,.13) 0 1px, transparent 1px),
                radial-gradient(circle at 50% 46%, transparent 27%, rgba(255,255,255,.10) 27%, rgba(255,255,255,.10) calc(27% + 1px), transparent calc(27% + 1px)),
                radial-gradient(circle at 50% 46%, transparent 40%, rgba(255,255,255,.07) 40%, rgba(255,255,255,.07) calc(40% + 1px), transparent calc(40% + 1px));
        }

        .mode .glyph {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -58%);
            font-size: 34px;
            line-height: 1;
            z-index: 1;
        }

        .mode .tile b {
            position: relative;
            z-index: 1;
            font-size: 15px;
            font-weight: 800;
            letter-spacing: -0.02em;
            color: #fff;
        }

        .mode h3 {
            font-size: 14px;
            font-weight: 700;
            margin-top: 12px;
            letter-spacing: -0.01em;
        }

        .mode p { color: var(--quiet); font-size: 13px; margin-top: 2px; }

        .t-creative    { background: linear-gradient(155deg, #c2410c, #7c2d12); }
        .t-storyteller { background: linear-gradient(155deg, #6d28d9, #4c1d95); }
        .t-teacher     { background: linear-gradient(155deg, #1d4ed8, #172554); }
        .t-homework    { background: linear-gradient(155deg, #047857, #064e3b); }
        .t-gamer       { background: linear-gradient(155deg, #be123c, #881337); }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 12px;
        }

        .card {
            background: var(--panel-soft);
            border: 1px solid var(--line);
            border-radius: 6px;
            padding: 22px;
        }

        .card .ico { font-size: 20px; line-height: 1; }

        .card h3 {
            font-size: 15px;
            font-weight: 800;
            letter-spacing: -0.02em;
            margin: 14px 0 6px;
        }

        .card p { color: var(--muted); font-size: 13px; }

        .flow { display: flex; flex-wrap: wrap; align-items: stretch; gap: 8px; }

        .step {
            flex: 1 1 170px;
            background: var(--panel-soft);
            border: 1px solid var(--line);
            border-radius: 6px;
            padding: 18px;
        }

        .step .n {
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.16em;
            color: var(--quiet);
        }

        .step h3 { font-size: 14px; font-weight: 800; margin: 10px 0 5px; letter-spacing: -0.02em; }
        .step p { color: var(--muted); font-size: 12.5px; }

        pre {
            background: #0a0a0a;
            border: 1px solid var(--line);
            border-radius: 6px;
            padding: 18px;
            overflow-x: auto;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 12.5px;
            color: var(--muted);
            line-height: 1.7;
        }

        pre b { color: var(--text); font-weight: 600; }

        footer {
            margin-top: 8px;
            padding: 30px 40px 40px;
            background: var(--panel);
            border-radius: var(--radius);
            color: var(--quiet);
            font-size: 12.5px;
        }

        footer a { color: var(--muted); text-decoration: none; }
        footer a:hover { color: var(--text); text-decoration: underline; }
        .foot-row { display: flex; flex-wrap: wrap; gap: 16px; justify-content: space-between; }

        @media (max-width: 640px) {
            .panel, .hero { padding: 28px 20px; }
            footer { padding: 24px 20px 32px; }
            .topbar { padding: 14px 16px; }
            .topnav a { padding: 8px; }
        }
    </style>
</head>
<body>
<div class="shell">

    <div class="topbar">
        <span class="brand">
            <svg width="26" height="26" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <rect x="1" y="1" width="30" height="30" rx="8" stroke="#fff" stroke-opacity=".25" stroke-width="1.5"/>
                <circle cx="11" cy="12" r="3.5" fill="#c2410c"/>
                <circle cx="21" cy="12" r="3.5" fill="#6d28d9"/>
                <circle cx="11" cy="21" r="3.5" fill="#047857"/>
                <circle cx="21" cy="21" r="3.5" fill="#be123c"/>
            </svg>
            Playroom
        </span>
        <nav class="topnav">
            <a href="/chat">Playground</a>
            <a href="/docs">API</a>
            <a href="https://github.com/behdadmehrnia/Playroom" target="_blank" rel="noopener">GitHub</a>
        </nav>
    </div>

    <div class="panel hero">
        <div class="overline">Playroom</div>
        <h1>A safe AI companion for children.</h1>
        <p class="lede">
            Five modes in one model — creative, storyteller, teacher, homework and games.
            Playroom routes to the right one on its own, grounds homework in the actual
            school textbook page, and reviews every reply for safety before a child sees it.
        </p>
        <div class="cta-row">
            <a class="btn-primary" href="/chat">Open the playground</a>
            <a class="btn-ghost" href="/docs">Read the API docs &rarr;</a>
        </div>
    </div>

    <section class="panel">
        <div class="section-head">
            <div class="overline">One model</div>
            <h2>Five ways to be alongside a child</h2>
            <p>Pick a mode, or let intent detection choose. Tools are gated per mode — the
               textbook and calculator belong to teaching, web search to play.</p>
        </div>
        <div class="modes">
            <a class="mode" href="/chat">
                <div class="tile t-creative"><span class="glyph">🎨</span><b>Creative</b></div>
                <h3>Ideas and making</h3>
                <p>Turns "I'm bored" into one small step</p>
            </a>
            <a class="mode" href="/chat">
                <div class="tile t-storyteller"><span class="glyph">📖</span><b>Storyteller</b></div>
                <h3>Short stories</h3>
                <p>Four to eight sentences, always a choice</p>
            </a>
            <a class="mode" href="/chat">
                <div class="tile t-teacher"><span class="glyph">📚</span><b>Teacher</b></div>
                <h3>Concepts</h3>
                <p>Everyday examples, one idea per step</p>
            </a>
            <a class="mode" href="/chat">
                <div class="tile t-homework"><span class="glyph">✏️</span><b>Homework</b></div>
                <h3>Method, not answers</h3>
                <p>Works the page, never hands over the result</p>
            </a>
            <a class="mode" href="/chat">
                <div class="tile t-gamer"><span class="glyph">🎮</span><b>Games</b></div>
                <h3>Play and puzzles</h3>
                <p>Word games, riddles, real game facts</p>
            </a>
        </div>
    </section>

    <section class="panel">
        <div class="section-head">
            <div class="overline">Capabilities</div>
            <h2>What makes it different</h2>
        </div>
        <div class="grid">
            <div class="card">
                <div class="ico">📚</div>
                <h3>Page-addressable textbooks</h3>
                <p>Ask for a page, lesson or chapter and the real page — text and image — is
                   retrieved from a local index. The image wins over OCR.</p>
            </div>
            <div class="card">
                <div class="ico">🛡️</div>
                <h3>Safety that outranks everything</h3>
                <p>A core prompt no persona or user instruction can override, plus a
                   reflection pass on every reply before it is sent.</p>
            </div>
            <div class="card">
                <div class="ico">🧭</div>
                <h3>Intent routing</h3>
                <p>A classifier picks the mode above a confidence floor, and sticks with it
                   mid-activity instead of flipping on a single word.</p>
            </div>
            <div class="card">
                <div class="ico">🔢</div>
                <h3>Checked arithmetic</h3>
                <p>Maths in a child's message is evaluated by a sandboxed tool, then used to
                   explain the steps — never to hand over the answer.</p>
            </div>
            <div class="card">
                <div class="ico">🔎</div>
                <h3>Web search with fallbacks</h3>
                <p>An ordered provider chain keeps game and world facts current, and the
                   model is told to say "I'm not sure" rather than guess.</p>
            </div>
            <div class="card">
                <div class="ico">⚡</div>
                <h3>Drop-in OpenAI API</h3>
                <p>Point any OpenAI-compatible client at it. Streaming replies over SSE,
                   with the active persona and diagnostics attached.</p>
            </div>
        </div>
    </section>

    <section class="panel">
        <div class="section-head">
            <div class="overline">Architecture</div>
            <h2>What happens to a message</h2>
        </div>
        <div class="flow">
            <div class="step">
                <div class="n">01</div><h3>Route</h3>
                <p>Persona from metadata, or intent detection above a 0.7 confidence floor.</p>
            </div>
            <div class="step">
                <div class="n">02</div><h3>Ground</h3>
                <p>Textbook page, web results, or a maths result — gated by the active mode.</p>
            </div>
            <div class="step">
                <div class="n">03</div><h3>Generate</h3>
                <p>The safety core, the persona prompt, and the retrieved context.</p>
            </div>
            <div class="step">
                <div class="n">04</div><h3>Review</h3>
                <p>A reflection agent judges safety only, and can send it back to be rewritten.</p>
            </div>
            <div class="step">
                <div class="n">05</div><h3>Stream</h3>
                <p>Chunks over SSE with live status, then a title for the conversation.</p>
            </div>
        </div>
    </section>

    <section class="panel">
        <div class="section-head">
            <div class="overline">Quick start</div>
            <h2>Talk to it like any OpenAI model</h2>
        </div>
        <pre><b>curl</b> -s http://localhost:8000/v1/chat/completions \\
  -H <b>'Content-Type: application/json'</b> \\
  -d <b>'{"messages":[{"role":"user","content":"tell me a story"}]}'</b></pre>
    </section>

    <footer>
        <div class="foot-row">
            <div>
                <div class="overline">Playroom</div>
                <p style="margin-top:8px">Built by <a href="https://github.com/behdadmehrnia" target="_blank" rel="noopener">Behdad</a> · MIT licensed</p>
            </div>
            <div style="display:flex;gap:16px;align-items:flex-start">
                <a href="/chat">Playground</a>
                <a href="/docs">API docs</a>
                <a href="/health">Health</a>
                <a href="https://github.com/behdadmehrnia/Playroom" target="_blank" rel="noopener">Source</a>
            </div>
        </div>
    </footer>

</div>
</body>
</html>
"""


CHAT_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <meta name="theme-color" content="#000000">
    <title>Playground — Playroom</title>
    <link rel="icon" type="image/svg+xml" href="/logo.svg">
    <script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js"></script>
    <style>
        :root {
            --bg: #000;
            --panel: #121212;
            --panel-soft: #181818;
            --panel-raised: #242424;
            --line: rgba(255, 255, 255, 0.08);
            --text: #fff;
            --muted: #b3b3b3;
            --quiet: #737373;
            --sidebar-width: 252px;
            --radius: 14px;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        html, body { height: 100%; }

        body {
            background: var(--bg);
            color: var(--text);
            font-family: "Circular", "Avenir Next", "Helvetica Neue", -apple-system,
                         BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            font-size: 14px;
            line-height: 1.55;
            -webkit-font-smoothing: antialiased;
            display: grid;
            grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
            gap: 8px;
            padding: 8px;
            overflow: hidden;
        }

        /* ---------- sidebar ---------- */

        .sidebar {
            background: var(--panel);
            border-radius: var(--radius);
            display: flex;
            flex-direction: column;
            min-height: 0;
            overflow: hidden;
        }

        .sidebar-top { padding: 14px; }

        .new-chat {
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            background: #fff;
            color: #000;
            border: 0;
            border-radius: 999px;
            padding: 11px 16px;
            font: inherit;
            font-weight: 800;
            letter-spacing: -0.01em;
            cursor: pointer;
            transition: transform .15s ease;
        }

        .new-chat:hover { transform: scale(1.03); }

        .session-list { flex: 1; min-height: 0; overflow-y: auto; padding: 0 8px 12px; }

        .session-list::-webkit-scrollbar { width: 8px; }
        .session-list::-webkit-scrollbar-thumb { background: #2a2a2a; border-radius: 8px; }

        .session-item {
            display: flex;
            align-items: center;
            gap: 4px;
            border-radius: 2px;
            padding: 0 2px 0 6px;
        }

        .session-item:hover { background: var(--panel-raised); }
        .session-item.active { background: var(--panel-raised); }

        .session-open {
            flex: 1;
            min-width: 0;
            background: none;
            border: 0;
            color: var(--muted);
            font: inherit;
            font-weight: 600;
            text-align: left;
            padding: 9px 4px;
            cursor: pointer;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .session-item.active .session-open, .session-item:hover .session-open { color: var(--text); }

        .session-del {
            flex: none;
            background: none;
            border: 0;
            color: var(--quiet);
            font: inherit;
            font-size: 15px;
            line-height: 1;
            padding: 6px 8px;
            border-radius: 2px;
            cursor: pointer;
            opacity: 0;
        }

        .session-item:hover .session-del { opacity: 1; }
        .session-del:hover { color: var(--text); }

        .session-empty { color: var(--quiet); font-size: 13px; padding: 12px 8px; }

        .sidebar-backdrop {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, .6);
            z-index: 40;
        }

        /* ---------- main ---------- */

        .main {
            background: var(--panel);
            border-radius: var(--radius);
            display: flex;
            flex-direction: column;
            min-width: 0;
            min-height: 0;
            overflow: hidden;
        }

        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 14px 20px;
            border-bottom: 1px solid var(--line);
            background: rgba(18, 18, 18, .78);
            backdrop-filter: blur(28px) saturate(1.6);
            -webkit-backdrop-filter: blur(28px) saturate(1.6);
        }

        .header-start { display: flex; align-items: center; gap: 8px; min-width: 0; }

        .brand {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: var(--text);
            text-decoration: none;
            font-weight: 800;
            font-size: 15px;
            letter-spacing: -0.03em;
        }

        .menu-toggle {
            display: none;
            background: none;
            border: 0;
            color: var(--text);
            font-size: 20px;
            line-height: 1;
            padding: 6px 8px;
            border-radius: 2px;
            cursor: pointer;
        }

        .persona-sep { color: var(--quiet); }

        .persona-wrap { position: relative; display: none; }
        .persona-wrap.visible { display: inline-flex; align-items: center; gap: 6px; }

        .persona-btn {
            background: none;
            border: 0;
            color: var(--muted);
            font: inherit;
            font-weight: 700;
            font-size: 13px;
            padding: 6px 10px;
            border-radius: 2px;
            cursor: pointer;
            white-space: nowrap;
        }

        .persona-btn:hover { color: var(--text); background: var(--panel-raised); }

        .persona-hint { display: none; color: var(--quiet); }
        .persona-hint.visible { display: inline-block; }

        .persona-menu {
            display: none;
            position: absolute;
            top: calc(100% + 8px);
            left: 0;
            z-index: 30;
            min-width: 210px;
            background: var(--panel-raised);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 6px;
            box-shadow: 0 18px 40px rgba(0, 0, 0, .55);
        }

        .persona-menu.open { display: block; }

        .persona-option {
            display: block;
            width: 100%;
            background: none;
            border: 0;
            color: var(--muted);
            font: inherit;
            font-weight: 600;
            text-align: left;
            padding: 9px 10px;
            border-radius: 2px;
            cursor: pointer;
        }

        .persona-option:hover { background: rgba(255, 255, 255, .07); color: var(--text); }
        .persona-option[aria-selected="true"] { color: var(--text); }

        .back { color: var(--quiet); text-decoration: none; font-weight: 700; font-size: 13px; }
        .back:hover { color: var(--text); }

        /* ---------- messages ---------- */

        #messages {
            flex: 1;
            min-height: 0;
            overflow-y: auto;
            padding: 28px 20px;
            display: flex;
            flex-direction: column;
            gap: 18px;
            scroll-behavior: smooth;
        }

        #messages::-webkit-scrollbar { width: 10px; }
        #messages::-webkit-scrollbar-thumb { background: #2a2a2a; border-radius: 10px; }

        .empty {
            margin: auto;
            text-align: center;
            color: var(--quiet);
            font-size: 15px;
            line-height: 1.8;
            max-width: 40ch;
        }

        .empty strong { color: var(--text); font-weight: 800; letter-spacing: -0.02em; }

        .bubble {
            max-width: min(760px, 92%);
            width: fit-content;
            word-wrap: break-word;
            overflow-wrap: anywhere;
        }

        .bubble.user {
            align-self: flex-end;
            background: var(--panel-raised);
            border-radius: 14px 14px 4px 14px;
            padding: 11px 16px;
        }

        .bubble.assistant { align-self: flex-start; color: var(--muted); }

        .bubble.typing { color: var(--quiet); font-style: italic; }

        .stream-cursor {
            display: inline-block;
            width: 7px;
            height: 1em;
            background: var(--text);
            vertical-align: -0.15em;
            margin-left: 2px;
            animation: blink 1s steps(2, start) infinite;
        }

        @keyframes blink { to { visibility: hidden; } }

        .bubble.assistant.md p { margin: 0 0 0.65em; }
        .bubble.assistant.md p:last-child { margin-bottom: 0; }
        .bubble.assistant.md ul,
        .bubble.assistant.md ol { margin: 0.4em 0 0.65em; padding-left: 1.3em; }
        .bubble.assistant.md li { margin: 0.2em 0; }
        .bubble.assistant.md strong { color: var(--text); font-weight: 700; }
        .bubble.assistant.md em { color: var(--text); }
        .bubble.assistant.md a { color: var(--text); }
        .bubble.assistant.md code {
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 0.9em;
            background: #0a0a0a;
            border: 1px solid var(--line);
            border-radius: 3px;
            padding: 1px 5px;
        }
        .bubble.assistant.md pre {
            background: #0a0a0a;
            border: 1px solid var(--line);
            border-radius: 6px;
            padding: 14px;
            overflow-x: auto;
            margin: 0.5em 0 0.8em;
        }
        .bubble.assistant.md pre code { border: none; background: transparent; padding: 0; }
        .bubble.assistant.md h1,
        .bubble.assistant.md h2,
        .bubble.assistant.md h3 {
            color: var(--text);
            font-size: 1.05em;
            font-weight: 800;
            letter-spacing: -0.02em;
            margin: 0.7em 0 0.35em;
        }
        .bubble.assistant.md blockquote {
            border-left: 2px solid var(--line);
            padding-left: 12px;
            color: var(--quiet);
            margin: 0.5em 0;
        }

        /* ---------- composer ---------- */

        form {
            display: flex;
            align-items: flex-end;
            gap: 10px;
            padding: 14px 20px 18px;
            border-top: 1px solid var(--line);
        }

        #input {
            flex: 1;
            resize: none;
            max-height: 180px;
            background: var(--panel-soft);
            border: 1px solid var(--line);
            border-radius: 12px;
            color: var(--text);
            font: inherit;
            padding: 13px 16px;
            outline: none;
            transition: border-color .15s ease;
        }

        #input::placeholder { color: var(--quiet); }
        #input:focus { border-color: rgba(255, 255, 255, .22); }

        #send {
            flex: none;
            background: #fff;
            color: #000;
            border: 0;
            border-radius: 999px;
            font: inherit;
            font-weight: 800;
            letter-spacing: -0.01em;
            padding: 13px 26px;
            cursor: pointer;
            transition: transform .15s ease, opacity .15s ease;
        }

        #send:hover:not(:disabled) { transform: scale(1.04); }
        #send:disabled { opacity: .45; cursor: not-allowed; }

        /* ---------- responsive ---------- */

        @media (max-width: 820px) {
            body { grid-template-columns: minmax(0, 1fr); }

            .sidebar {
                position: fixed;
                top: 8px;
                bottom: 8px;
                left: 8px;
                width: var(--sidebar-width);
                z-index: 50;
                transform: translateX(calc(-100% - 16px));
                transition: transform .22s ease;
            }

            body.sidebar-open .sidebar { transform: translateX(0); }
            body.sidebar-open .sidebar-backdrop { display: block; }

            .menu-toggle { display: block; }
            #messages { padding: 20px 14px; }
            form { padding: 12px 14px 16px; }
            #send { padding: 13px 20px; }
        }
    </style>
</head>
<body>
    <div class="sidebar-backdrop" id="sidebarBackdrop"></div>
    <aside class="sidebar" id="sidebar">
        <div class="sidebar-top">
            <button type="button" class="new-chat" id="newChatBtn">＋ New chat</button>
        </div>
        <div class="session-list" id="sessionList"></div>
    </aside>

    <div class="main">
        <header>
            <div class="header-start">
                <button type="button" class="menu-toggle" id="menuToggle" aria-label="Conversations">☰</button>
                <a class="brand" href="/">
                    <svg width="22" height="22" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                        <rect x="1" y="1" width="30" height="30" rx="8" stroke="#fff" stroke-opacity=".25" stroke-width="1.5"/>
                        <circle cx="11" cy="11.5" r="3.6" fill="#c2410c"/>
                        <circle cx="21" cy="11.5" r="3.6" fill="#6d28d9"/>
                        <circle cx="11" cy="21" r="3.6" fill="#047857"/>
                        <circle cx="21" cy="21" r="3.6" fill="#be123c"/>
                    </svg>
                    Playroom
                </a>
                <div class="persona-wrap" id="personaWrap">
                    <span class="persona-sep">·</span>
                    <button type="button" class="persona-btn" id="personaBtn" aria-haspopup="listbox" aria-expanded="false" title="Choose a mode">Mode</button>
                    <div class="persona-menu" id="personaMenu" role="listbox"></div>
                </div>
                <button type="button" class="persona-btn persona-hint" id="personaHint" title="Choose a mode">· Choose a mode</button>
            </div>
            <a class="back" href="/">Back</a>
        </header>

        <div id="messages"></div>

        <form id="form">
            <textarea id="input" rows="1" placeholder="Write your message..." autofocus></textarea>
            <button type="submit" id="send">Send</button>
        </form>
    </div>
    <script>
        const STORAGE_KEY = 'playroom_chat_v1';
        const COOKIE_PREFIX = 'ykc_';
        const COOKIE_META = 'ykc_n';
        const MAX_SESSIONS = 30;
        const MAX_MESSAGES = 80;
        const MAX_CONTENT = 12000;

        const messagesEl = document.getElementById('messages');
        const form = document.getElementById('form');
        const input = document.getElementById('input');
        const sendBtn = document.getElementById('send');
        const personaWrap = document.getElementById('personaWrap');
        const personaBtn = document.getElementById('personaBtn');
        const personaMenu = document.getElementById('personaMenu');
        const personaHint = document.getElementById('personaHint');
        const sessionList = document.getElementById('sessionList');
        const newChatBtn = document.getElementById('newChatBtn');
        const menuToggle = document.getElementById('menuToggle');
        const sidebarBackdrop = document.getElementById('sidebarBackdrop');

        const FALLBACK_PERSONAS = [
            { value: 'auto', label: '✨ Auto' },
            { value: 'creative', label: '🎨 Creative' },
            { value: 'storyteller', label: '📖 Storyteller' },
            { value: 'teacher', label: '📚 Teacher' },
            { value: 'homework', label: '✏️ Homework' },
            { value: 'gamer', label: '🎮 Games' },
        ];
        let personas = FALLBACK_PERSONAS.slice();
        let selectedPersona = 'auto';
        let activePersona = null;
        let history = [];
        let store = { activeId: null, selectedPersona: 'auto', sessions: [] };
        let requestToken = 0;
        let isBusy = false;

        if (window.marked) marked.setOptions({ breaks: true, gfm: true });

        function setBusy(busy) {
            isBusy = !!busy;
            document.body.classList.toggle('is-busy', isBusy);
            sendBtn.disabled = isBusy;
            newChatBtn.disabled = isBusy;
            renderSessionList();
        }

        function uid() {
            return 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
        }

        function getCookie(name) {
            const parts = document.cookie.split('; ');
            for (let i = 0; i < parts.length; i++) {
                const row = parts[i];
                const eq = row.indexOf('=');
                if (eq === -1) continue;
                if (row.slice(0, eq) === name) return row.slice(eq + 1);
            }
            return null;
        }
        function delCookie(name) {
            document.cookie = name + '=; path=/; max-age=0; SameSite=Lax';
        }
        function clearLegacyCookies() {
            const nRaw = getCookie(COOKIE_META);
            const n = nRaw ? parseInt(decodeURIComponent(nRaw), 10) || 0 : 0;
            for (let i = 0; i < Math.max(n, 40); i++) delCookie(COOKIE_PREFIX + i);
            delCookie(COOKIE_META);
            delCookie('playroom_chat');
        }
        function readLegacyCookies() {
            const nRaw = getCookie(COOKIE_META);
            const n = nRaw ? parseInt(decodeURIComponent(nRaw), 10) || 0 : 0;
            if (!n) {
                const legacy = getCookie('playroom_chat');
                return legacy ? decodeURIComponent(legacy) : '';
            }
            let encoded = '';
            for (let i = 0; i < n; i++) {
                const part = getCookie(COOKIE_PREFIX + i);
                if (part == null) return '';
                encoded += part;
            }
            try { return decodeURIComponent(encoded); } catch (_) { return ''; }
        }

        function sessionById(id) {
            return store.sessions.find((s) => s.id === id) || null;
        }
        function getCurrentSession() {
            return sessionById(store.activeId);
        }

        function isDefaultTitle(title) {
            return !title || title === 'New chat';
        }

        function touchSession(session, messages, persona, actPersona, titleHint) {
            if (!session) return;
            session.messages = (messages || []).map((m) => ({
                role: m.role,
                content: String(m.content || ''),
            }));
            session.persona = persona || 'auto';
            session.activePersona = actPersona || null;
            session.updatedAt = Date.now();
            if (titleHint && String(titleHint).trim()) {
                session.title = String(titleHint).trim().slice(0, 60);
            } else if (isDefaultTitle(session.title)) {
                const firstUser = session.messages.find((m) => m.role === 'user');
                if (firstUser) {
                    session.title = firstUser.content.trim().slice(0, 40) || 'New chat';
                } else {
                    session.title = 'New chat';
                }
            }
        }

        function cloneStoreForPersist(state) {
            return {
                activeId: state.activeId,
                selectedPersona: state.selectedPersona || 'auto',
                sessions: (state.sessions || [])
                    .slice()
                    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
                    .slice(0, MAX_SESSIONS)
                    .map((s) => ({
                        id: s.id,
                        title: String(s.title || 'New chat').slice(0, 60),
                        updatedAt: s.updatedAt || 0,
                        persona: s.persona || 'auto',
                        activePersona: s.activePersona || null,
                        messages: (s.messages || []).slice(-MAX_MESSAGES).map((m) => ({
                            role: m.role,
                            content: String(m.content || '').slice(0, MAX_CONTENT),
                        })),
                    })),
            };
        }

        function saveStore() {
            const current = getCurrentSession();
            if (current) {
                touchSession(current, history, selectedPersona, activePersona);
            }
            store.selectedPersona = selectedPersona;
            const persistable = cloneStoreForPersist(store);
            try {
                localStorage.setItem(STORAGE_KEY, JSON.stringify(persistable));
            } catch (err) {
                // Quota exceeded: drop oldest non-active sessions and retry.
                let sessions = persistable.sessions.slice();
                while (sessions.length > 1) {
                    const drop = sessions.filter((s) => s.id !== persistable.activeId).pop();
                    if (!drop) break;
                    sessions = sessions.filter((s) => s.id !== drop.id);
                    try {
                        localStorage.setItem(STORAGE_KEY, JSON.stringify({
                            ...persistable,
                            sessions,
                        }));
                        store.sessions = sessions.map((ps) => {
                            const live = sessionById(ps.id);
                            return live || ps;
                        });
                        renderSessionList();
                        return;
                    } catch (_) { /* continue shrinking */ }
                }
                console.warn('playroom chat storage full', err);
            }
            renderSessionList();
        }

        function normalizeLoaded(data) {
            if (!data || !Array.isArray(data.sessions)) return null;
            return {
                activeId: data.activeId || (data.sessions[0] && data.sessions[0].id) || null,
                selectedPersona: data.selectedPersona || 'auto',
                sessions: data.sessions.map((s) => ({
                    id: s.id,
                    title: s.title || 'New chat',
                    updatedAt: s.updatedAt || 0,
                    persona: s.persona || 'auto',
                    activePersona: s.activePersona || null,
                    messages: Array.isArray(s.messages) ? s.messages.slice() : [],
                })),
            };
        }

        function loadStore() {
            try {
                const rawLs = localStorage.getItem(STORAGE_KEY);
                if (rawLs) {
                    const parsed = normalizeLoaded(JSON.parse(rawLs));
                    if (parsed) {
                        store = parsed;
                        return;
                    }
                }
            } catch (_) {}

            // Migrate older cookie-based store once, then clear cookies.
            try {
                const rawCookie = readLegacyCookies();
                if (rawCookie) {
                    const parsed = normalizeLoaded(JSON.parse(rawCookie));
                    if (parsed) {
                        store = parsed;
                        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(cloneStoreForPersist(store))); } catch (_) {}
                        clearLegacyCookies();
                        return;
                    }
                }
            } catch (_) {}
        }

        function ensureSession() {
            let s = getCurrentSession();
            if (s) return s;
            s = {
                id: uid(),
                title: 'New chat',
                updatedAt: Date.now(),
                persona: selectedPersona,
                activePersona: activePersona,
                messages: [],
            };
            store.sessions.unshift(s);
            store.activeId = s.id;
            return s;
        }

        function effectivePersona() {
            if (activePersona && activePersona !== 'none') return activePersona;
            if (selectedPersona && selectedPersona !== 'auto') return selectedPersona;
            return null;
        }

        function applyResolvedPersona(resolved) {
            if (!resolved || resolved === 'none') return;
            activePersona = resolved;
            // Keep chip + future requests in sync with the live chat persona,
            // even if the user had manually picked something earlier.
            selectedPersona = resolved;
            store.selectedPersona = resolved;
            updatePersonaChip();
            renderPersonaMenu();
        }

        function loadSessionIntoUi(session) {
            history = (session && session.messages) ? session.messages.slice() : [];
            selectedPersona = (session && session.persona) || 'auto';
            activePersona = (session && session.activePersona) || null;
            // Prefer showing the last known active persona for this session.
            if ((!activePersona || activePersona === 'none') && selectedPersona !== 'auto') {
                activePersona = selectedPersona;
            }
            store.selectedPersona = selectedPersona;
            renderMessages();
            updatePersonaChip();
            renderPersonaMenu();
        }

        function createSession() {
            if (isBusy) return;
            const prev = getCurrentSession();
            if (prev) touchSession(prev, history, selectedPersona, activePersona);

            const s = {
                id: uid(),
                title: 'New chat',
                updatedAt: Date.now(),
                persona: 'auto',
                activePersona: null,
                messages: [],
            };
            store.sessions.unshift(s);
            store.activeId = s.id;
            selectedPersona = 'auto';
            activePersona = null;
            history = [];
            saveStore();
            renderMessages();
            updatePersonaChip();
            renderPersonaMenu();
            closeSidebarMobile();
            input.focus();
        }

        function switchSession(id) {
            if (isBusy) return;
            if (store.activeId === id) {
                closeSidebarMobile();
                return;
            }
            const prev = getCurrentSession();
            if (prev) touchSession(prev, history, selectedPersona, activePersona);

            store.activeId = id;
            const s = getCurrentSession();
            if (!s) return;
            loadSessionIntoUi(s);
            saveStore();
            closeSidebarMobile();
            input.focus();
        }

        function deleteSession(id) {
            if (isBusy) return;
            if (store.activeId === id) {
                const prev = getCurrentSession();
                if (prev) touchSession(prev, history, selectedPersona, activePersona);
            }
            store.sessions = store.sessions.filter((s) => s.id !== id);
            if (store.activeId === id) {
                if (store.sessions.length) {
                    store.sessions.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
                    store.activeId = store.sessions[0].id;
                    loadSessionIntoUi(store.sessions[0]);
                } else {
                    store.activeId = null;
                    history = [];
                    selectedPersona = 'auto';
                    activePersona = null;
                    ensureSession();
                    renderMessages();
                    updatePersonaChip();
                    renderPersonaMenu();
                }
            }
            saveStore();
        }

        function renderSessionList() {
            sessionList.innerHTML = '';
            if (!store.sessions.length) {
                const empty = document.createElement('div');
                empty.className = 'session-empty';
                empty.textContent = 'No conversations yet';
                sessionList.appendChild(empty);
                return;
            }
            store.sessions
                .slice()
                .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
                .forEach((s) => {
                    const row = document.createElement('div');
                    row.className = 'session-item' + (s.id === store.activeId ? ' active' : '');
                    const openBtn = document.createElement('button');
                    openBtn.type = 'button';
                    openBtn.className = 'session-open';
                    openBtn.textContent = s.title || 'New chat';
                    openBtn.title = isBusy ? 'Wait for the reply to finish' : (s.title || 'New chat');
                    openBtn.disabled = isBusy;
                    openBtn.addEventListener('click', () => switchSession(s.id));
                    const delBtn = document.createElement('button');
                    delBtn.type = 'button';
                    delBtn.className = 'session-del';
                    delBtn.setAttribute('aria-label', 'Delete');
                    delBtn.textContent = '×';
                    delBtn.disabled = isBusy;
                    delBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        deleteSession(s.id);
                    });
                    row.appendChild(openBtn);
                    row.appendChild(delBtn);
                    sessionList.appendChild(row);
                });
        }

        function renderEmpty() {
            const empty = document.createElement('div');
            empty.className = 'empty';
            empty.id = 'empty';
            empty.innerHTML = 'Talk to <strong>Playroom</strong>.<br>Write your question to get started.';
            messagesEl.appendChild(empty);
        }

        function renderMessages() {
            messagesEl.innerHTML = '';
            if (!history.length) {
                renderEmpty();
                return;
            }
            history.forEach((m) => {
                if (m.role === 'user') addBubble('user', m.content, null, false, false);
                else addBubble('assistant', m.content, null, true, false);
            });
            messagesEl.scrollTop = messagesEl.scrollHeight;
        }

        function labelFor(value) {
            const hit = personas.find((p) => p.value === value);
            return hit ? hit.label : (value || '');
        }
        function shortLabel(value) {
            const full = labelFor(value);
            const parts = full.trim().split(/\\s+/);
            return parts.length > 1 ? parts.slice(1).join(' ') : full;
        }
        function updatePersonaChip() {
            const showValue = effectivePersona();
            if (showValue) {
                personaWrap.classList.add('visible');
                personaHint.hidden = true;
                personaBtn.textContent = shortLabel(showValue);
            } else {
                personaWrap.classList.remove('visible');
                personaHint.hidden = false;
            }
        }
        function renderPersonaMenu() {
            personaMenu.innerHTML = '';
            const current = effectivePersona() || selectedPersona || 'auto';
            personas.forEach((p) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'persona-option' + (p.value === current ? ' active' : '');
                btn.textContent = p.label;
                btn.setAttribute('role', 'option');
                btn.addEventListener('click', () => {
                    selectedPersona = p.value;
                    activePersona = p.value !== 'auto' ? p.value : null;
                    closePersonaMenu();
                    updatePersonaChip();
                    renderPersonaMenu();
                    saveStore();
                });
                personaMenu.appendChild(btn);
            });
        }
        function openPersonaMenu() {
            if (!personaWrap.classList.contains('visible')) {
                personaWrap.classList.add('visible');
                personaHint.hidden = true;
                const show = effectivePersona() || selectedPersona || 'auto';
                personaBtn.textContent = shortLabel(show);
            }
            personaMenu.classList.add('open');
            personaBtn.classList.add('open');
            personaBtn.setAttribute('aria-expanded', 'true');
        }
        function closePersonaMenu() {
            personaMenu.classList.remove('open');
            personaBtn.classList.remove('open');
            personaBtn.setAttribute('aria-expanded', 'false');
            updatePersonaChip();
        }

        personaBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (personaMenu.classList.contains('open')) closePersonaMenu();
            else openPersonaMenu();
        });
        personaHint.addEventListener('click', (e) => {
            e.stopPropagation();
            openPersonaMenu();
        });
        document.addEventListener('click', () => closePersonaMenu());
        personaMenu.addEventListener('click', (e) => e.stopPropagation());

        function openSidebarMobile() { document.body.classList.add('sidebar-open'); }
        function closeSidebarMobile() { document.body.classList.remove('sidebar-open'); }
        menuToggle.addEventListener('click', () => {
            if (document.body.classList.contains('sidebar-open')) closeSidebarMobile();
            else openSidebarMobile();
        });
        sidebarBackdrop.addEventListener('click', closeSidebarMobile);
        newChatBtn.addEventListener('click', createSession);

        async function loadPersonas() {
            try {
                const res = await fetch('/v1/personas');
                if (!res.ok) return;
                const data = await res.json();
                if (Array.isArray(data.personas) && data.personas.length) {
                    personas = data.personas.map((p) => ({ value: p.value, label: p.label }));
                    if (!personas.some((p) => p.value === 'auto')) {
                        personas.unshift({ value: 'auto', label: '✨ Auto' });
                    }
                }
            } catch (_) {}
            renderPersonaMenu();
            updatePersonaChip();
        }

        function stripPersonaMarkers(text) {
            // Keep markers in stored history; strip only for on-screen rendering.
            return String(text || '')
                .replace(/<!--\\s*playroom:[a-z_]+\\s*-->/gi, '')
                .replace(/\\u200b\\u200d\\u200c\\u200b[\\u200b\\u200c\\u200d]{2}\\u200b\\u200d\\u200c\\u200b/g, '')
                .replace(/\\u2060[\\u200b\\u200c\\u200d]{2}\\u2060/g, '')
                .replace(/[\\u2060\\ufeff]/g, '')
                .replace(/\\s+$/g, '');
        }

        function renderMarkdown(text) {
            const clean = stripPersonaMarkers(text);
            if (window.marked && window.DOMPurify) {
                return DOMPurify.sanitize(marked.parse(String(clean || '')));
            }
            return String(clean || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/\\n/g, '<br>');
        }

        function addBubble(role, text, extraClass, asMarkdown, scroll) {
            const empty = document.getElementById('empty');
            if (empty) empty.remove();
            const div = document.createElement('div');
            div.className = 'bubble ' + role + (extraClass ? ' ' + extraClass : '');
            const displayText = role === 'assistant' ? stripPersonaMarkers(text) : text;
            if (asMarkdown) {
                div.classList.add('md');
                div.innerHTML = renderMarkdown(displayText);
            } else {
                div.textContent = displayText;
            }
            messagesEl.appendChild(div);
            if (scroll !== false) messagesEl.scrollTop = messagesEl.scrollHeight;
            return div;
        }

        function autoResize() {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 140) + 'px';
        }
        input.addEventListener('input', autoResize);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                form.requestSubmit();
            }
        });

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const text = input.value.trim();
            if (!text || isBusy || sendBtn.disabled) return;

            const session = ensureSession();
            const sessionId = session.id;
            const token = ++requestToken;

            addBubble('user', text);
            history.push({ role: 'user', content: text });
            touchSession(session, history, selectedPersona, activePersona);
            saveStore();

            input.value = '';
            autoResize();
            setBusy(true);
            const typing = addBubble('assistant', 'Thinking...', 'typing');

            const messagesForRequest = history.slice();
            const personaForRequest = selectedPersona;
            const stickyPersona = activePersona;

            const payload = { messages: messagesForRequest, stream: true };
            if (personaForRequest && personaForRequest !== 'auto') {
                payload.persona = personaForRequest;
                payload.metadata = {
                    playroom_persona: personaForRequest,
                    playroom_active_persona: personaForRequest,
                };
            } else if (stickyPersona && stickyPersona !== 'none') {
                payload.metadata = { playroom_active_persona: stickyPersona };
            }

            const failRequest = (detail) => {
                const target = sessionById(sessionId);
                if (!target) {
                    if (typing && typing.parentNode) typing.remove();
                    return;
                }
                const msgs = (target.messages || []).slice();
                if (msgs.length && msgs[msgs.length - 1].role === 'user' && msgs[msgs.length - 1].content === text) {
                    msgs.pop();
                }
                touchSession(target, msgs, target.persona, target.activePersona);
                if (token === requestToken && store.activeId === sessionId) {
                    if (typing && typing.parentNode) typing.remove();
                    history = msgs.slice();
                    addBubble('assistant', String(detail), 'error');
                } else if (typing && typing.parentNode) {
                    typing.remove();
                }
                saveStore();
            };

            try {
                const res = await fetch('/v1/chat/completions', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'text/event-stream',
                    },
                    body: JSON.stringify(payload),
                });

                if (!res.ok) {
                    const data = await res.json().catch(() => ({}));
                    const detail = (data && (data.detail || data.error || data.message)) || ('Error ' + res.status);
                    failRequest(detail);
                    return;
                }

                if (!res.body) {
                    failRequest('No streaming response from the server.');
                    return;
                }

                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                let reply = '';
                let shown = '';
                let resolved = null;
                let chatTitle = null;
                let streamBubble = null;
                let revealTimer = null;
                const STREAM_TICK_MS = 16;

                const isActiveView = () =>
                    token === requestToken && store.activeId === sessionId;

                const ensureStreamBubble = () => {
                    if (!isActiveView()) return null;
                    if (streamBubble && streamBubble.parentNode) return streamBubble;
                    if (typing && typing.parentNode) {
                        typing.classList.remove('typing');
                        typing.classList.add('md', 'streaming');
                        typing.textContent = '';
                        streamBubble = typing;
                    } else {
                        streamBubble = addBubble('assistant', '', 'streaming', true, false);
                    }
                    return streamBubble;
                };

                const paintShown = () => {
                    const el = ensureStreamBubble();
                    if (!el) return;
                    el.innerHTML = renderMarkdown(shown) + '<span class="stream-cursor" aria-hidden="true"></span>';
                    messagesEl.scrollTop = messagesEl.scrollHeight;
                };

                const stopReveal = () => {
                    if (revealTimer) {
                        window.clearInterval(revealTimer);
                        revealTimer = null;
                    }
                };

                // Advance ``shown`` by one word (Persian/Latin) or one whitespace/punct run.
                const nextWordEnd = (full, from) => {
                    if (from >= full.length) return full.length;
                    const rest = full.slice(from);
                    const ws = rest.match(/^\\s+/);
                    if (ws) return from + ws[0].length;
                    const word = rest.match(/^[\\u0600-\\u06FF\\u0750-\\u077F\\u08A0-\\u08FF\\uFB50-\\uFDFF\\uFE70-\\uFEFFa-zA-Z0-9۰-۹٠-٩_]+/);
                    if (word) return from + word[0].length;
                    return from + 1;
                };

                try {
                const scheduleReveal = () => {
                    if (revealTimer) return;
                    revealTimer = window.setInterval(() => {
                        if (shown.length >= reply.length) {
                            stopReveal();
                            paintShown();
                            return;
                        }
                        shown = reply.slice(0, nextWordEnd(reply, shown.length));
                        paintShown();
                    }, STREAM_TICK_MS);
                };

                const waitUntilCaughtUp = () => new Promise((resolve) => {
                    const tick = () => {
                        if (shown.length >= reply.length) {
                            stopReveal();
                            resolve();
                            return;
                        }
                        scheduleReveal();
                        window.setTimeout(tick, STREAM_TICK_MS);
                    };
                    tick();
                });

                const consumeSseLine = (line) => {
                    const trimmed = String(line || '').trim();
                    if (!trimmed || !trimmed.startsWith('data:')) return;
                    const dataStr = trimmed.slice(5).trim();
                    if (!dataStr || dataStr === '[DONE]') return;
                    let chunk;
                    try {
                        chunk = JSON.parse(dataStr);
                    } catch (_) {
                        return;
                    }
                    const delta = chunk?.choices?.[0]?.delta?.content;
                    if (typeof delta === 'string' && delta) {
                        reply += delta;
                        scheduleReveal();
                    }
                    const meta = chunk?.playroom;
                    if (meta && typeof meta === 'object') {
                        if (meta.persona) resolved = meta.persona;
                        if (meta.chat_title) chatTitle = meta.chat_title;
                        if (meta.error && !reply) reply = String(meta.error);
                    }
                };

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const parts = buffer.split('\\n');
                    buffer = parts.pop() || '';
                    for (const line of parts) consumeSseLine(line);
                }
                if (buffer.trim()) consumeSseLine(buffer);
                await waitUntilCaughtUp();

                if (!reply.trim()) {
                    stopReveal();
                    failRequest('No reply received.');
                    return;
                }

                const target = sessionById(sessionId);
                if (!target) {
                    if (typing && typing.parentNode) typing.remove();
                    return;
                }

                const msgs = (target.messages || []).slice();
                msgs.push({ role: 'assistant', content: reply });
                let nextActive = target.activePersona;
                if (resolved && resolved !== 'none') nextActive = resolved;
                const nextPersona = (resolved && resolved !== 'none') ? resolved : target.persona;
                touchSession(target, msgs, nextPersona, nextActive, chatTitle);

                if (isActiveView()) {
                    shown = reply;
                    if (streamBubble && streamBubble.parentNode) {
                        streamBubble.classList.remove('streaming');
                        streamBubble.innerHTML = renderMarkdown(reply);
                    } else if (typing && typing.parentNode) {
                        typing.remove();
                        addBubble('assistant', reply, null, true);
                    } else {
                        addBubble('assistant', reply, null, true);
                    }
                    history = msgs.slice();
                    if (resolved && resolved !== 'none') applyResolvedPersona(resolved);
                } else if (typing && typing.parentNode) {
                    typing.remove();
                }
                saveStore();
                } catch (streamErr) {
                    stopReveal();
                    throw streamErr;
                }
            } catch (err) {
                failRequest('Could not reach the server. Please try again.');
            } finally {
                if (token === requestToken) {
                    setBusy(false);
                    input.focus();
                }
            }
        });

        // boot
        loadStore();
        ensureSession();
        loadSessionIntoUi(getCurrentSession());
        saveStore();
        loadPersonas();
    </script>
</body>
</html>
"""



@router.get("/", response_class=HTMLResponse)
async def landing_page() -> HTMLResponse:
    """Playroom landing page — what it is, and a way into the playground."""
    return HTMLResponse(content=LANDING_PAGE_HTML)


@router.get("/chat", response_class=HTMLResponse)
async def chat_playground() -> HTMLResponse:
    """The built-in chat playground, talking to the OpenAI-compatible endpoint."""
    return HTMLResponse(content=CHAT_PAGE_HTML)


@router.get("/logo.svg", include_in_schema=False)
async def logo() -> Response:
    """Serve the Playroom mark, used as the favicon on both pages."""
    return Response(
        content=LOGO_PATH.read_text(encoding="utf-8"),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )
