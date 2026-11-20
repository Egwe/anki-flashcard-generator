# Anki Flashcard Generator

Ein CLI-Werkzeug, das aus lokalen Dokumenten mit KI überprüfbare Karteikarten und direkt importierbare **Anki-`.apkg`-Dateien** erzeugt. Neue Decks lassen sich erstellen und vorhandene Pakete gezielt erweitern.

## Projektdokumente und aktueller Stand

- [requirements.md](./requirements.md) bündelt alle ursprünglichen und neuen Anforderungen, ihren Status und die Abnahmekriterien.
- [AGENTS.md](./AGENTS.md) enthält die verbindlichen Regeln für Architektur, Never Nesting, Docstrings, Konfiguration, Tests und kleine Commits.
- Diese README beschreibt kompakt die **aktuell implementierte** Bedienung.
- [docs/benutzerhandbuch.html](./docs/benutzerhandbuch.html) ist das ausführliche Benutzerhandbuch mit einfachen Erklärungen, allen Befehlen und Optionen, Suchfunktion und kopierbaren Beispielen. Öffne die Datei direkt in einem Browser; kein Server ist erforderlich.
- [docs/entwicklerhandbuch.html](./docs/entwicklerhandbuch.html) ist das Entwicklerhandbuch: Architektur, alle Module und Funktionen, ein Ablaufdiagramm vom Befehl bis zum APKG, Konfigurationsauflösung, Teststrategie, Erweiterungsrezepte sowie geprüfte Randfälle. Ebenfalls ohne Server im Browser nutzbar.

Der erste MVP ist funktionsfähig. Never Nesting, kleine fachliche Einheiten und vollständige Funktions-/Klassendokumentation sind im Bestand umgesetzt und durch Ruff abgesichert. Die zentrale YAML-Konfiguration ist einschließlich Modellprofilen, Prioritäten, Pfaden und Diagnose vollständig in die CLI integriert. Native PDF-Verarbeitung ist für ausdrücklich freigegebene OpenAI-Modelle implementiert; lokale Extraktion bleibt Standard. Die strukturierte lokale PDF-Aufbereitung mit Docling (OCR, Tabellen, Formeln, Bildbeschreibungen) ist als optionaler Modus `structured` verfügbar. Die Web-Oberfläche und das Proxmox-/Container-Deployment entstehen im eigenen Projekt Anki Studio; dieses Paket stellt dafür einen oberflächenfreien Ablaufdienst bereit.

## Warum Python?

Python verbindet hier drei passende Ökosysteme: Dokumentverarbeitung (`pypdf`, `python-docx`), Anki-Dateien (`genanki` und die offizielle `anki`-API) sowie viele KI-Anbieter über `litellm`. Die fachliche Kernlogik ist von Typer, dem CLI-Framework, getrennt. Dadurch kann später eine Web-API, Desktop- oder Web-Oberfläche denselben Kern verwenden.

## Funktionsumfang

- Eingabe: **PDF, DOCX, HTML, Markdown und Text**
- Ausgabe: direkt importierbares **APKG**, kein manueller CSV-/TSV-Import nötig
- neue Decks erstellen oder ein vorhandenes APKG atomar erweitern
- klassische und zstd-komprimierte Anki-Sammlungen lesen
- KI-Anbieter über ein einheitliches `provider/modell`-Format
- OpenAI, Anthropic, Google Gemini, Moonshot, Ollama und weitere LiteLLM-Provider
- Kartenlimit, Sprache, zusätzliche Anweisungen und konfigurierbare Textaufteilung (`--chunk-size` 1.000–100.000 Zeichen; 500 Zeichen Überlappung, höchstens ein Viertel des Abschnitts)
- JSON-Zwischendatei zur Prüfung und zum erneuten Export ohne weitere KI-Kosten
- Duplikaterkennung beim Generieren und Erweitern
- Deckliste mit Kartenanzahl anzeigen
- optional: PDFs lokal mit Docling vollständig aufbereiten – Text in Bildern per OCR, Tabellen als Markdown-Tabellen, Formeln als LaTeX, Abbildungen als markierte Beschreibungen; an das Kartenmodell geht nur Text
- optional: KI ordnet Karten inhaltlich passenden Unterdecks zu (`Vorlesung::Kapitel`) und nutzt beim Erweitern die vorhandenen Unterdecks als Kontext

## Installation

Voraussetzung ist **Python 3.11 oder neuer**.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Für Entwicklung und Tests:

```bash
python -m pip install -e '.[dev]'
```

Die virtuelle Umgebung und lokale `.env`-Dateien sind von Git ausgeschlossen.

Für die strukturierte PDF-Aufbereitung (`--pdf-mode structured`) werden zusätzlich das optionale Extra `pdf` mit Docling und **eine GPU** benötigt, die PyTorch nutzen kann (NVIDIA CUDA, AMD über ROCm, Apple Silicon über MPS oder Intel XPU). Installiere zuerst PyTorch passend zu deiner GPU; den Befehl liefert die Auswahl auf [pytorch.org](https://pytorch.org/get-started/locally/). `--no-cache-dir` verhindert, dass pip Kopien in `~/.cache/pip` ablegt:

```bash
.venv/bin/python -m pip install --no-cache-dir torch torchvision   # Befehl je nach GPU von pytorch.org
.venv/bin/python -m pip install --no-cache-dir -e '.[pdf]'
anki-flashcards models download   # Modelle vorab nach ./models laden (optional)
```

Ohne GPU ist der Modus nicht vorgesehen (siehe unten). Wer ihn trotzdem mit `--allow-cpu` nutzen will, installiert die kleinere CPU-Variante mit `--index-url https://download.pytorch.org/whl/cpu`.

## Schnellstart mit lokalem Ollama

Ollama muss separat laufen und das gewählte Modell muss lokal verfügbar sein, beispielsweise nach `ollama pull llama3.2`. Ein API-Schlüssel ist dafür nicht erforderlich.

```bash
anki-flashcards generate ./skript.pdf \
  --output ./output/biologie.apkg \
  --deck 'Biologie::Grundlagen' \
  --model ollama/llama3.2 \
  --limit 50 \
  --language Deutsch \
  --json ./output/biologie.cards.json
```

Die erzeugte `.apkg` kann anschließend direkt in Anki importiert werden.

## CLI-Workflows

### 1. Dokument in ein neues Deck umwandeln

```bash
anki-flashcards generate dokument.docx \
  --output output/mein-deck.apkg \
  --deck 'Mein Deck' \
  --model openai/gpt-4o-mini \
  --limit 50
```

Der Standardname des Decks ist der Dateiname ohne Endung. Ein bereits vorhandener Ausgabepfad wird nicht versehentlich überschrieben.

Weitere Beispiele:

```bash
# Zusätzlicher fachlicher Fokus
anki-flashcards generate kapitel.html -o output/kapitel.apkg \
  -m anthropic/claude-sonnet-4-5 \
  --instructions 'Bevorzuge Verständnisfragen und kurze Antworten.'

# Ohne festes Kartenlimit; bewusst und sparsam einsetzen
anki-flashcards generate notizen.md -o output/notizen.apkg \
  -m ollama/llama3.2 --limit 0
```

`--limit 0` bedeutet **unbegrenzt**: Jeder Dokumentabschnitt wird einmal verarbeitet; die KI erstellt so viele sinnvolle Karten, wie die Quelle ihrer Einschätzung nach hergibt. Die Voreinstellung ist sicherer: **50 Karten**.

### 2. Vorhandenes APKG erweitern

```bash
anki-flashcards generate weiteres-kapitel.pdf \
  --output output/mein-deck.apkg \
  --extend \
  --deck 'Mein Deck' \
  --model gemini/gemini-2.5-flash \
  --limit 25
```

`--extend` verlangt eine vorhandene Datei. Der Deckname muss dem gewünschten Zieldeck entsprechen; falls er fehlt, wird ein neues Deck innerhalb des Pakets angelegt. Vorhandene Karten, Medien-Einträge und Lernstände bleiben erhalten. Fragen werden normalisiert verglichen, damit Duplikate trotz Groß-/Kleinschreibung oder abweichender Leerzeichen übersprungen werden.

Vor dem Import eines erweiterten Decks ist zusätzlich eine Anki-Sicherung sinnvoll. Das Werkzeug arbeitet an der angegebenen APKG-Datei, nicht direkt an der persönlichen Anki-Sammlung.

### 3. JSON prüfen und ohne KI exportieren

Beim Generieren mit `--json` entsteht eine versionierte Datei mit `schema_version`, Decknamen und Karten. Tags aus mehreren Wörtern – in KI-Antworten wie in dieser Datei – werden zu einem Tag mit Unterstrichen zusammengezogen (`Ohmsches_Gesetz`), weil Anki keine Leerzeichen in Tags kennt. Nach einer manuellen Prüfung oder Bearbeitung:

```bash
anki-flashcards export output/biologie.cards.json \
  --output output/biologie.apkg \
  --deck 'Biologie::Grundlagen'
```

Auch dieser Befehl unterstützt `--extend`.

### 4. Vorlesung mit KI-Unterdecks aufbauen

Mit `--subdecks` ist `--deck` das übergeordnete Deck, etwa der Name einer Vorlesung. Das Modell ordnet jede Karte genau einem Unterdeck `Deck::Kapitel` zu und orientiert sich dabei an Kapitel- und Abschnittsüberschriften der Quelle. Mehrere Dokumente werden nacheinander verarbeitet:

```bash
# Erstes Skript: neues Paket, Unterdecks entstehen aus den Kapiteln
anki-flashcards generate vl-01.pdf -o output/el1.apkg -d 'Elektrotechnik 1' --subdecks

# Weitere Skripte: vorhandene Unterdecks werden erkannt und bevorzugt wiederverwendet
anki-flashcards generate vl-02.pdf -o output/el1.apkg -d 'Elektrotechnik 1' --subdecks --extend
```

Beim Erweitern liest das Programm die vorhandenen direkten Unterdecks des Decks und je Unterdeck bis zu fünf Beispielfragen aus dem APKG und sendet sie zusammen mit dem Text an das Modell. Neue Unterdecks entstehen nur für Inhalte, die zu keinem vorhandenen passen; Namen, die sich nur in Groß-/Kleinschreibung oder Leerraum unterscheiden, werden vereinheitlicht. Doppelte Fragen werden dann im ganzen Deck einschließlich aller Unterdecks erkannt. Die Ausgabe listet die neuen Karten je Unterdeck. Ein Unterdeckname hat genau eine Ebene (kein `::`) und höchstens 100 Zeichen; verletzt das Modell diese Regel, bricht der Lauf mit einer Fehlermeldung ab. Ohne `--subdecks` bleibt alles wie bisher. In YAML entspricht das `generation.subdecks: true`; `--no-subdecks` schaltet es für einen Aufruf wieder ab. Das Karten-JSON enthält dann je Karte das Feld `subdeck`, und `export` legt diese Karten wieder unter `--deck::subdeck` ab.

### 5. Decks eines Pakets anzeigen

```bash
anki-flashcards decks output/mein-deck.apkg
```

### Alle Optionen

```bash
anki-flashcards --help
anki-flashcards generate --help
anki-flashcards export --help
anki-flashcards decks --help
anki-flashcards models download --help
```

Die Hilfe funktioniert auch mit `-h` und enthält Beispiele, Pflicht- und optionsabhängige Werte, Standardwerte, Wertebereiche sowie das Verhalten bei neuen oder bestehenden Ausgabedateien. Erfolgreiche Befehle verwenden Exit-Code **0**, erwartete Anwendungs-/Providerfehler **1** und ungültige CLI-Nutzung **2**. Erwartete Fehler erscheinen ohne unnötigen Traceback auf `stderr`.

## Zentrale YAML-Konfiguration

[config.example.yaml](./config.example.yaml) enthält sichere, direkt aktivierbare Modellbausteine für Ollama, OpenAI, Anthropic, Gemini und Moonshot. [.env.example](./.env.example) enthält die zugehörigen Credential-Platzhalter und die Links zu den Token-Verwaltungsseiten der Anbieter. Der Service in `config.py` lädt versionierte YAML-Dateien, validiert unbekannte Felder und Werte strikt, löst Modellprofile auf und speichert Änderungen atomar. API-Schlüssel werden nicht gespeichert; `api_key_env` enthält ausschließlich den Namen der zugehörigen Umgebungsvariablen.

Die Konfiguration wird mit `--config PFAD` oder `ANKI_CONFIG=PFAD` ausgewählt. Ohne Angabe wird eine optionale `config.yaml` im aktuellen Arbeitsverzeichnis gelesen; ohne diese Datei gelten die bisherigen Defaults und Workflows unverändert. Eine ausdrücklich angegebene fehlende Datei ist ein Fehler.

Die Priorität ist **eingebauter Default → YAML/Profil → ausdrücklicher CLI-Wert**. `--model` überschreibt das Profilmodell; `--extend/--no-extend` überschreibt YAML in beiden Richtungen. Auch `--limit 0` und eine leere `--instructions ''` gelten als explizite CLI-Werte. `.env` ist ausschließlich für Zugangsdaten vorgesehen und überschreibt keine Modelle oder Endpunkte. Die alten Variablen `ANKI_MODEL` und `LLM_API_BASE` werden nicht ausgewertet.

Relative `input_dir`- und `output_dir`-Pfade werden relativ zur YAML-Datei aufgelöst. Ein reiner Eingabedateiname wird unter `input_dir` gesucht; ausdrückliche relative CLI-Pfade bleiben relativ zum aktuellen Arbeitsverzeichnis. Ohne `--output` wird `<eingabedateiname>.apkg` unter `output_dir` angelegt. `generation.deck` kann auch für `export` den Decknamen vorgeben.

Beispiel mit Konfiguration:

```bash
cp config.example.yaml config.yaml
anki-flashcards generate skript.pdf --config config.yaml --limit 25 --no-extend
anki-flashcards export biologie.cards.json --config config.yaml
anki-flashcards config show skript.pdf --config config.yaml --output output/deck.apkg
```

`config show` gibt die effektiven Werte und ihre Herkunft (`built-in`, `config`, `cli`) als JSON aus. API-Schlüssel werden ausschließlich als `set (hidden)` beziehungsweise `not set` dargestellt, niemals mit ihrem Wert. `--profile NAME` wählt ein bestimmtes YAML-Profil.

## KI-Provider und Zugangsdaten vorbereiten

Die YAML-Datei ist die Hauptkonfiguration für Modell, Endpunkt, Timeout, PDF-Modus und Provider-Optionen. `.env` enthält nur geheime Zugangsdaten. Diese Trennung verhindert, dass ein alter Modellname aus `.env` unbemerkt das YAML-Profil überschreibt.

1. Kopiere beide Beispieldateien:

   ```bash
   cp config.example.yaml config.yaml
   cp .env.example .env
   ```

2. Wähle in `config.yaml` ein Profil mit `default_profile`. Passe `model` und `api_base` an. Für Ollama muss das Modell bereits auf dem Server installiert sein. Cloud-Modelle benötigen ein Konto und einen API-Token des jeweiligen Anbieters.
3. Trage in `.env` nur den benötigten Token ein. Der Profilschlüssel `api_key_env` verweist auf den Namen dieser Variablen, nicht auf ihren Wert.
4. Prüfe die effektive Konfiguration vor dem ersten Lauf:

   ```bash
   anki-flashcards config show dokument.pdf --config config.yaml
   ```

Die Beispieldateien enthalten bereits Standardendpunkte, Profilfelder und kommentierte Optionen:

| Anbieter | Beispielmodell in YAML | Standardendpunkt | Credential in `.env` |
| --- | --- | --- | --- |
| Ollama | `ollama_chat/qwen3.6:27b` | `http://localhost:11434` | normalerweise keiner |
| OpenAI | `openai/gpt-4o-mini` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| Anthropic | `anthropic/claude-sonnet-4-5` | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini/gemini-2.5-flash` | `https://generativelanguage.googleapis.com` | `GEMINI_API_KEY` |
| Moonshot | `moonshot/moonshot-v1-8k` | `https://api.moonshot.ai/v1` | `MOONSHOT_API_KEY` |
| Eigener kompatibler Server | `openai/dein-modellname` | `http://localhost:8000/v1` | `CUSTOM_LLM_API_KEY` |

`--model`, `--profile` und `--api-base` überschreiben die YAML-Werte für den aktuellen Aufruf. Die verfügbaren Modellnamen und unterstützten Optionen können sich ändern. Maßgeblich sind die Modelllisten des Anbieters und die [LiteLLM-Provider-Dokumentation](https://docs.litellm.ai/docs/providers). Anfragen verwenden strukturierte JSON-Ausgaben, zwei Wiederholversuche und einen konfigurierbaren Timeout. Die Antwort wird mit Pydantic validiert.

## Strukturierte lokale PDF-Aufbereitung (Docling)

`--pdf-mode structured` beziehungsweise `pdf_mode: structured` löst ein Problem des Standardmodus: `local` liest nur die eingebettete Textebene einer PDF. Text in Bildern und Scans, grafische Inhalte, Tabellenstrukturen und Formeln gehen dabei verloren oder kommen verstümmelt an. Der strukturierte Modus wandelt die PDF stattdessen **lokal** mit [Docling](https://github.com/docling-project/docling) (MIT-Lizenz) in Markdown um:

- Layoutanalyse mit Überschriften und Lesereihenfolge, auch bei mehrspaltigen Seiten
- Texterkennung (OCR, RapidOCR) für Bildbereiche und gescannte Seiten; `--force-ocr` liest jede Seite per OCR
- Tabellen als Markdown-Tabellen mit Zeilen und Spalten
- Formeln als LaTeX (`--no-formulas` schaltet die langsame Formelerkennung ab; Formeln erscheinen dann als `[Formel S. N – nicht ausgewertet]`)
- Abbildungen als markierte Beschreibung an ihrer Stelle, z. B. `[Abbildung S. 12 – Beschreibung: …; Text im Bild: …]`
- Logos, Icons und auf vielen Seiten wiederkehrende Bilder sowie wiederkehrende Kopf- und Fußzeilen werden ausgelassen
- jede Seite beginnt mit `[Seite N]`

**Der Modus braucht eine GPU.** Vor Modell-Downloads und Aufbereitung prüft das Programm, ob PyTorch einen Beschleuniger (CUDA, ROCm, MPS oder XPU) nutzen kann, und setzt ihn für Docling und das lokale Bildmodell ein. Ohne GPU bricht der Lauf sofort mit einem Hinweis auf die beiden Alternativen ab:

- `--pdf-mode native`: Das KI-Modell des Providers liest die Original-PDF samt Seitenbildern (Upload, nur freigegebene OpenAI-Modelle).
- `--pdf-mode local`: Nur die eingebettete Textebene wird gelesen; Bilder, Scans und Formeln fehlen.

`--allow-cpu` (YAML `pdf_conversion.allow_cpu`) erzwingt den CPU-Betrieb trotzdem, etwa für kurze Dokumente oder mit `--no-formulas`.

Danach durchläuft der Text unverändert Textaufteilung, Kartenerzeugung, Validierung, Unterdeck-Zuordnung und APKG-Ausgabe. Der Modus funktioniert daher mit **jedem** Kartenmodell, auch mit reinen Textmodellen über Ollama. Das Kartenmodell erhält den Hinweis, dass Abbildungsbeschreibungen maschinell erstellt sind und nichts darüber hinaus erfunden werden darf. Nur `.pdf`-Dateien werden angenommen; für Markdown oder Text gilt `--pdf-mode local`.

```bash
anki-flashcards generate input/EL1_WS26_V03.pdf \
  --output output/el1.apkg --deck EL1 --subdecks \
  --pdf-mode structured \
  --source-text output/texte/EL1_WS26_V03.md
```

Nach der Aufbereitung meldet die CLI Seiten, OCR-Seiten, Tabellen, Formeln sowie beschriebene und ausgelassene Abbildungen. `--source-text DATEI.md` (oder `pdf_conversion.source_text_dir`) speichert den aufbereiteten Text atomar in eine **neue** Datei. So lässt sich die Vollständigkeit prüfen und von Hand korrigieren. Die Datei kann danach mit `--pdf-mode local` wie jede Markdown-Datei erneut verarbeitet werden, ohne die Aufbereitung zu wiederholen.

**Nichts geht stillschweigend verloren:** Kann ein Element nicht gelesen werden, etwa eine Formel ohne Ergebnis oder eine Abbildung ohne Beschreibung, bricht der Lauf vor jeder KI-Anfrage mit einer Liste ab. `--allow-unreadable` setzt stattdessen gemeldete Platzhalter `[nicht lesbar: …]`. Fehlt Docling, nennt die CLI den Installationsbefehl. Es gibt keinen stillen Wechsel zu `local` oder `native`.

### Bildmodelle

Welches Modell Abbildungen beschreibt, ist austauschbar (`--picture-backend`, YAML `pdf_conversion.pictures.backend`):

| Backend | Wirkung | Datenfluss |
| --- | --- | --- |
| `local` (Standard) | Bild-Sprach-Modell läuft im Programm; Standard `HuggingFaceTB/SmolVLM-256M-Instruct`, jede Hugging-Face-Kennung über `pictures.model` | bleibt auf dem Rechner |
| `profile` | ein Modellprofil aus `models` beschreibt, z. B. ein Vision-Modell in Ollama auf einem Server, das Kartenprofil oder eine eigene OpenAI-kompatible API; `--picture-profile NAME` oder `pictures.profile`, sonst das Kartenprofil | Bildausschnitte – nie die ganze PDF – gehen an den Provider des Profils; die CLI kündigt das an |
| `none` | keine Beschreibung; die Abbildung bleibt als `[Abbildung S. N – nicht beschrieben; Text im Bild: …]` erhalten | bleibt auf dem Rechner |

Ein Profil für Bilder muss `image_input: true` setzen. Das Programm vermutet Bildfähigkeit nie anhand des Modellnamens und bricht sonst vor der Aufbereitung ab. `config.example.yaml` enthält dafür das Beispielprofil `ollama-vision`. Weitere Backends lassen sich hinter der Schnittstelle `PictureDescriber` ergänzen, ohne Kartenerzeugung oder APKG-Ausgabe zu ändern.

**Ehrliche Einschätzung der Bildbeschreibung:** Kleine lokale Modelle laufen auf der CPU, verstehen technische Abbildungen aber schlecht und erfinden teilweise Inhalte. Mit SmolVLM-256M ergab der Test an den Vorlesungsfolien keine verlässlichen Beschreibungen von Schaltbildern oder Diagrammen. Der Text in Abbildungen wird unabhängig davon per OCR übernommen. Für brauchbare Beschreibungen empfiehlt sich `--picture-backend profile` mit einem größeren Vision-Modell (etwa 7B) auf einem Server mit ausreichend Arbeitsspeicher oder GPU. Ohne ein solches Modell ist `--picture-backend none` die vorsichtigere Wahl.

### Modelle und Speicherort

Alles, was der Modus herunterlädt oder zwischenspeichert, liegt in **einem** Ordner: `pdf_conversion.models_dir`, standardmäßig `models/` neben der YAML-Datei. Ohne YAML-Datei gilt `models/` im aktuellen Arbeitsverzeichnis. Das betrifft Docling-Modelle (`models/docling`), Bildmodelle (`models/pictures`) und die Caches von Hugging Face, PyTorch und Docling. Das Programm setzt `HF_HOME`, `TORCH_HOME`, `XDG_CACHE_HOME` und `DOCLING_CACHE_DIR` für seinen eigenen Prozess und schreibt nichts in `~/.cache`. `models/` steht in `.gitignore`. Der erste Download wird angekündigt; `models download` lädt alles vorab, danach arbeitet der Modus offline. Modelle, die Ollama verwaltet, bleiben in Ollamas eigener Ablage.

### Laufzeit und Ressourcen

Warum eine GPU nötig ist, zeigt die Messung auf einem Laptop **ohne nutzbare GPU** (Ryzen 5 PRO 4650U, 12 Threads, 14 GB RAM) mit den Vorlesungsfolien aus `input/`:

- Installation: rund 2,2 GB in `.venv` (PyTorch CPU, Docling); Modelle rund 1,9 GB in `models/` (Docling inklusive Formelmodell 1,4 GB, SmolVLM-256M 0,5 GB)
- Layout, Text, Tabellen und OCR ohne Formeln: etwa 8–12 Sekunden pro Seite
- Formelerkennung: auf formelreichen Folien rund 2 Minuten pro Seite; eine 15-seitige EL1-Vorlesung war nach über 50 Minuten noch nicht fertig und wurde abgebrochen
- lokale Bildbeschreibung (SmolVLM-256M): etwa 15–25 Sekunden pro Abbildung
- Arbeitsspeicher: etwa 2,5–3 GB während der Aufbereitung

Die integrierte Radeon-Vega-GPU dieses Laptops (`gfx90c`) hilft nicht: ROCm unterstützt sie nicht offiziell, und sie hat nur 512 MiB eigenen Speicher. Modelle mit etwa 2B Parametern brauchten über 4 GB Arbeitsspeicher und brachten den Rechner in den Swap. Für größere Bildmodelle eignet sich das Backend `profile` mit einem eigenen Server.

## Native PDF-Verarbeitung

`--pdf-mode native` beziehungsweise `pdf_mode: native` überspringt die lokale PDF-Textextraktion und lädt die **vollständige Originaldatei** ausdrücklich zum konfigurierten Provider hoch. Standard ist weiterhin `local`. Nicht unterstützte Provider oder Modelle werden vor jeder Übertragung abgelehnt; es gibt keinen stillen Fallback auf lokale Extraktion oder ein anderes Modell.

### Geprüfte Fähigkeitenmatrix

Stand der Dokumentationsprüfung: **2026-11-17**.

| Provider | Freigegebene Modelle und Snapshots | PDF-Fähigkeit | Strukturierte Ausgabe | Grenzen/Status |
| --- | --- | --- | --- | --- |
| OpenAI | `gpt-4o-mini`, `gpt-4o`, `gpt-4.1`; nur datierte Snapshots derselben Basismodelle, z. B. `gpt-4o-mini-2024-07-18` | Responses API `input_file` mit Datei-ID; Text und Seitenbilder | `responses.parse` mit Pydantic `CardBatch` | Datei kleiner als 50 MiB; Modellkontextfenster zusätzlich beachten; Modelle derzeit von OpenAI als Deprecated markiert |

Keine pauschale Freigabe für andere OpenAI-Modelle oder Audio-/Realtime-Varianten: Diese benötigen eine neue Prüfung und einen eigenen Eintrag. Anthropic, Gemini, Moonshot und Ollama verwenden bis zu ihrer eigenen belegten Implementierung weiterhin `local`.

Quellen:

- [OpenAI File Inputs](https://developers.openai.com/api/docs/guides/file-inputs) – Datei-ID, Vision-Modelle, 50-MiB-Grenze und Tokenverbrauch
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) – `responses.parse` und Pydantic-Schema
- [OpenAI Python SDK Helpers](https://github.com/openai/openai-python/blob/main/helpers.md) – `output_parsed`
- [OpenAI Data Controls](https://developers.openai.com/api/docs/guides/your-data) – Dateien bleiben bis zur Löschung gespeichert; Abuse-Monitoring kann separate Aufbewahrung haben
- [OpenAI Files Delete](https://developers.openai.com/api/reference/resources/files/methods/delete) – Löschung hochgeladener Dateien
- [LiteLLM PDF Input](https://docs.litellm.ai/docs/completion/document_understanding) – Providerübergreifender Hintergrund; der native Adapter verwendet direkt das offizielle OpenAI-SDK

### Datenschutz und Ablauf

Vor dem Upload prüft der Adapter zusätzlich die Profil-`options`: Sie gehen im nativen Modus an `responses.parse` der OpenAI Responses API, nicht an LiteLLM. Deshalb heißt die Ausgabegrenze dort `max_output_tokens` statt `max_tokens`. Unbekannte oder vom Programm selbst gesetzte Optionen (`model`, `input`, `instructions`, `text_format`, `store`, `timeout`) werden mit einer klaren Meldung abgelehnt, bevor die Datei übertragen wird.

Der Adapter lädt mit `purpose=user_data`, fordert dieselbe validierte `CardBatch`-Struktur an und setzt `store=false` bei der Responses-Anfrage. Anschließend wird die hochgeladene Datei über die Files-API gelöscht – auch nach einem Anfragefehler. Schlägt die Löschung fehl, erscheint eine Warnung mit Datei-ID zur manuellen Bereinigung.

Die Dateiübertragung kann Token- und Uploadkosten verursachen; Text und Seitenbilder erhöhen den Kontextverbrauch. `store=false` und Löschung beseitigen nicht automatisch providerseitige Abuse-Monitoring-Aufbewahrung. Für vertrauliche Dokumente bleibt lokale Extraktion mit einem lokalen Modell vorzuziehen.

Beispiel:

```bash
anki-flashcards generate dokument.pdf \
  --output output/native.apkg \
  --profile openai-native-pdf \
  --config config.yaml \
  --limit 50
```

## Architektur

```text
Dokument → Textextraktion → Chunks → LiteLLM → validierte Karten
                                                    ↓
                                             optionales JSON
                                                    ↓
                                      genanki / offizielle Anki-API
                                                    ↓
                                                   APKG
```

- Kartentext wird HTML-escaped, damit Zeichen wie `<`, `>` und `&` als Text erscheinen.
- `config.py`: UI-unabhängiges YAML-Schema, Modellprofile und atomare Speicherung
- `settings.py`: Prioritäten, Profil-/Umgebungsauflösung, Pfadregeln und Diagnosedaten
- `documents.py`: Dateiformate, Normalisierung und überlappende Textabschnitte
- `ai.py`: Provider-Anbindung, Prompting und Antwortvalidierung
- `subdecks.py`: Unterdeck-Modus – Regeln, Kontext im Prompt, Antwortschema und einheitliche Unterdecknamen
- `native_pdf.py`: konservative Modellfreigabe sowie OpenAI-Upload, Responses-Parsing und Löschung
- `docling_pdf.py`: einzige Docling-Schnittstelle – Konvertierung, Bildausschnitte, Modell-Downloads und Bildmodell-Auswahl
- `structured_pdf.py`: setzt Seiten, Abbildungs- und Formelmarker zusammen, filtert Wiederholungen und meldet Unlesbares
- `pictures.py`: austauschbare Bildmodelle (`local`, `profile`) hinter der Schnittstelle `PictureDescriber`
- `model_storage.py`: projektlokaler Modellordner, Cache-Variablen und Download-Manifest
- `models.py`: Karten- und JSON-Schema sowie Deduplizierung
- `apkg.py`: Erstellung, Erweiterung und Inspektion von Anki-Paketen
- `pipeline.py`: vollständige Abläufe von `generate`, `export` und `models download` ohne Oberfläche; Fortschritt als Ereignisse, Abbruch, getrenntes Erzeugen und Schreiben
- `cli.py`: ausschließlich Kommandozeilen-Optionen und Darstellung der Ereignisse

Diagramme und Einzelheiten zu jedem Modul stehen im [Entwicklerhandbuch](./docs/entwicklerhandbuch.html). Die Kernfunktionen akzeptieren normale Python-Objekte und sind deshalb ohne CLI aufrufbar. Die Web-Oberfläche entsteht als eigenes Projekt „Anki Studio“ und nutzt `pipeline.py` direkt; Ziel, Entscheidungen und Schnittstellen stehen in [docs/anki-studio-uebergabe.md](./docs/anki-studio-uebergabe.md).

## Qualität und Tests

Ruff prüft neben Lint und Formatierung auch Modul-, Funktions-, Methoden- und Klassen-Docstrings sowie eine zyklomatische Komplexität von höchstens 8 pro Funktion. Die Projektregeln verlangen flachen Kontrollfluss und kleine fachliche Einheiten.

```bash
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest
```

Die Tests verwenden einen simulierten KI-Client und benötigen keine API-Schlüssel. Sie prüfen unter anderem Dokumentextraktion, Kartenlimits, JSON-Validierung, APKG-Erstellung und -Erweiterung, Duplikate, Lernstand-Erhalt, Medien-Einträge und zstd-Komprimierung. Der strukturierte PDF-Modus wird mit Attrappen für Docling, Bildmodelle und Downloads getestet; der reguläre Testlauf braucht weder Docling noch Modelle noch Netzwerk. Ein gesondert markierter Integrationstest mit echtem Docling und einer erzeugten Scan-Seite läuft nur ausdrücklich mit `python -m pytest -m docling`; fehlende Modelle lädt er nach `models/`.

## Bewusste MVP-Grenzen und nächste sinnvolle Schritte

- Im Standardmodus `local` werden nur eingebettete PDF-Texte gelesen; gescannte Seiten, Bildinhalte und Tabellenstrukturen erfasst erst `--pdf-mode structured`. Dieser Modus braucht eine GPU, und kleine lokale Bildmodelle beschreiben technische Abbildungen unzuverlässig (siehe oben). Ohne GPU bleiben `native` und `local`.
- URLs, Bilder/Audio in Karten, Lückentext und frei wählbare Notiztypen sind noch nicht enthalten.
- KI-Ergebnisse müssen fachlich geprüft werden. Die JSON-Datei ist dafür der empfohlene Zwischenschritt.
- Bei Cloud-Providern werden Dokumentauszüge an den jeweiligen Anbieter übertragen. Für vertrauliche Dokumente ist ein lokales Modell wie Ollama vorzusehen. Im Unterdeck-Modus mit `--extend` gehen zusätzlich die Namen vorhandener Unterdecks und einige Beispielfragen daraus an den Provider.
- Als nächste Ausbaustufen bieten sich Quellenangaben pro Karte, eine interaktive Kartenprüfung, ein Zwischenspeicher für aufbereitete PDFs, Cloze-Karten und ein Fortsetzen abgebrochener Generierungen an.
- Web-UI und Linux-Container/Proxmox-Deployment sind nicht Teil dieses Repositorys. Sie entstehen im eigenen Projekt Anki Studio (siehe [Übergabe](./docs/anki-studio-uebergabe.md)).
