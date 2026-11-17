# Anki Flashcard Generator

Ein CLI-Werkzeug, das aus lokalen Dokumenten mit KI überprüfbare Karteikarten und direkt importierbare **Anki-`.apkg`-Dateien** erzeugt. Neue Decks lassen sich erstellen und vorhandene Pakete gezielt erweitern.

## Projektdokumente und aktueller Stand

- [requirements.md](./requirements.md) bündelt alle ursprünglichen und neuen Anforderungen, ihren Status und die Abnahmekriterien.
- [AGENTS.md](./AGENTS.md) enthält die verbindlichen Regeln für Architektur, Never Nesting, Docstrings, Konfiguration, Tests und kleine Commits.
- Diese README beschreibt kompakt die **aktuell implementierte** Bedienung.
- [docs/benutzerhandbuch.html](./docs/benutzerhandbuch.html) ist das ausführliche Benutzerhandbuch mit einfachen Erklärungen, allen Befehlen und Optionen, Suchfunktion und kopierbaren Beispielen. Öffne die Datei direkt in einem Browser; kein Server ist erforderlich.

Der erste MVP ist funktionsfähig. Never Nesting, kleine fachliche Einheiten und vollständige Funktions-/Klassendokumentation sind im Bestand umgesetzt und durch Ruff abgesichert. Die zentrale YAML-Konfiguration ist einschließlich Modellprofilen, Prioritäten, Pfaden und Diagnose vollständig in die CLI integriert. Native PDF-Verarbeitung ist für ausdrücklich freigegebene OpenAI-Modelle implementiert; lokale Extraktion bleibt Standard. Web-UI und Proxmox-/Container-Deployment sind weiterhin spätere Ausbaustufen.

## Warum Python?

Python verbindet hier drei passende Ökosysteme: Dokumentverarbeitung (`pypdf`, `python-docx`), Anki-Dateien (`genanki` und die offizielle `anki`-API) sowie viele KI-Anbieter über `litellm`. Die fachliche Kernlogik ist von Typer, dem CLI-Framework, getrennt. Dadurch kann später eine Web-API, Desktop- oder Web-Oberfläche denselben Kern verwenden.

## Funktionsumfang

- Eingabe: **PDF, DOCX, HTML, Markdown und Text**
- Ausgabe: direkt importierbares **APKG**, kein manueller CSV-/TSV-Import nötig
- neue Decks erstellen oder ein vorhandenes APKG atomar erweitern
- klassische und zstd-komprimierte Anki-Sammlungen lesen
- KI-Anbieter über ein einheitliches `provider/modell`-Format
- OpenAI, Anthropic, Google Gemini, Moonshot, Ollama und weitere LiteLLM-Provider
- Kartenlimit, Sprache, zusätzliche Anweisungen und konfigurierbare Textaufteilung
- JSON-Zwischendatei zur Prüfung und zum erneuten Export ohne weitere KI-Kosten
- Duplikaterkennung beim Generieren und Erweitern
- Deckliste mit Kartenanzahl anzeigen

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

Beim Generieren mit `--json` entsteht eine versionierte Datei mit `schema_version`, Decknamen und Karten. Nach einer manuellen Prüfung oder Bearbeitung:

```bash
anki-flashcards export output/biologie.cards.json \
  --output output/biologie.apkg \
  --deck 'Biologie::Grundlagen'
```

Auch dieser Befehl unterstützt `--extend`.

### 4. Decks eines Pakets anzeigen

```bash
anki-flashcards decks output/mein-deck.apkg
```

### Alle Optionen

```bash
anki-flashcards --help
anki-flashcards generate --help
anki-flashcards export --help
anki-flashcards decks --help
```

Die Hilfe funktioniert auch mit `-h` und enthält Beispiele, Pflicht- und optionsabhängige Werte, Standardwerte, Wertebereiche sowie das Verhalten bei neuen oder bestehenden Ausgabedateien. Erfolgreiche Befehle verwenden Exit-Code **0**, erwartete Anwendungs-/Providerfehler **1** und ungültige CLI-Nutzung **2**. Erwartete Fehler erscheinen ohne unnötigen Traceback auf `stderr`.

## Zentrale YAML-Konfiguration

[config.example.yaml](./config.example.yaml) enthält sichere, direkt aktivierbare Modellbausteine für Ollama, OpenAI, Anthropic, Gemini und Moonshot. Der Service in `config.py` lädt versionierte YAML-Dateien, validiert unbekannte Felder und Werte strikt, löst Modellprofile auf und speichert Änderungen atomar. API-Schlüssel werden nicht gespeichert; `api_key_env` enthält ausschließlich den Namen der zugehörigen Umgebungsvariablen.

Die Konfiguration wird mit `--config PFAD` oder `ANKI_CONFIG=PFAD` ausgewählt. Ohne Angabe wird eine optionale `config.yaml` im aktuellen Arbeitsverzeichnis gelesen; ohne diese Datei gelten die bisherigen Defaults und Workflows unverändert. Eine ausdrücklich angegebene fehlende Datei ist ein Fehler.

Die Priorität ist **eingebauter Default → YAML/Profil → Umgebung/`.env` → ausdrücklicher CLI-Wert**. `--model` und `ANKI_MODEL` überschreiben das Profilmodell; `--extend/--no-extend` überschreibt YAML in beiden Richtungen. Auch `--limit 0` und eine leere `--instructions ''` gelten als explizite CLI-Werte.

Relative `input_dir`- und `output_dir`-Pfade werden relativ zur YAML-Datei aufgelöst. Ein reiner Eingabedateiname wird unter `input_dir` gesucht; ausdrückliche relative CLI-Pfade bleiben relativ zum aktuellen Arbeitsverzeichnis. Ohne `--output` wird `<eingabedateiname>.apkg` unter `output_dir` angelegt. `generation.deck` kann auch für `export` den Decknamen vorgeben.

Beispiel mit Konfiguration:

```bash
cp config.example.yaml config.yaml
anki-flashcards generate skript.pdf --config config.yaml --limit 25 --no-extend
anki-flashcards export biologie.cards.json --config config.yaml
anki-flashcards config show skript.pdf --config config.yaml --output output/deck.apkg
```

`config show` gibt die effektiven Werte und ihre Herkunft (`built-in`, `config`, `environment`, `cli`) als JSON aus. API-Schlüssel werden ausschließlich als `set (hidden)` beziehungsweise `not set` dargestellt, niemals mit ihrem Wert. `--profile NAME` wählt ein bestimmtes YAML-Profil.

## KI-Provider konfigurieren

Das Modell wird als `provider/modell` angegeben und entweder über `--model` oder `ANKI_MODEL` gesetzt. Schlüssel stehen in einer lokalen `.env` oder in der Umgebung; sie werden nicht in das APKG oder die JSON-Datei geschrieben.

```bash
cp .env.example .env
```

Beispiele:

| Anbieter | `ANKI_MODEL` | Umgebungsvariable |
| --- | --- | --- |
| Ollama | `ollama/llama3.2` | kein Schlüssel nötig |
| OpenAI | `openai/gpt-4o-mini` | `OPENAI_API_KEY` |
| Anthropic | `anthropic/claude-sonnet-4-5` | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini/gemini-2.5-flash` | `GEMINI_API_KEY` |
| Moonshot | `moonshot/kimi-k2-0711-preview` | `MOONSHOT_API_KEY` |

Die verfügbaren Modellnamen ändern sich unabhängig von diesem Projekt. Maßgeblich sind die Modelllisten des jeweiligen Anbieters und die [LiteLLM-Provider-Dokumentation](https://docs.litellm.ai/docs/providers).

Für einen kompatiblen eigenen Endpunkt können zusätzlich gesetzt werden:

```dotenv
LLM_API_BASE=http://localhost:11434
LLM_API_KEY=optionaler-schluessel
```

Alternativ ist `--api-base` verfügbar. Anfragen verwenden strukturierte JSON-Ausgaben, zwei Wiederholversuche und einen konfigurierbaren Timeout. Die Antwort wird mit Pydantic validiert.

## Native PDF-Verarbeitung

`--pdf-mode native` beziehungsweise `pdf_mode: native` überspringt die lokale PDF-Textextraktion und lädt die **vollständige Originaldatei** ausdrücklich zum konfigurierten Provider hoch. Standard ist weiterhin `local`. Nicht unterstützte Provider oder Modelle werden vor jeder Übertragung abgelehnt; es gibt keinen stillen Fallback auf lokale Extraktion oder ein anderes Modell.

### Geprüfte Fähigkeitenmatrix

Stand der Dokumentationsprüfung: **2026-11-17**.

| Provider | Freigegebene Modelle und Snapshots | PDF-Fähigkeit | Strukturierte Ausgabe | Grenzen/Status |
| --- | --- | --- | --- | --- |
| OpenAI | `gpt-4o-mini`, `gpt-4o`, `gpt-4.1`; nur datierte Snapshots derselben Basismodelle | Responses API `input_file` mit Datei-ID; Text und Seitenbilder | `responses.parse` mit Pydantic `CardBatch` | Datei kleiner als 50 MiB; Modellkontextfenster zusätzlich beachten; Modelle derzeit von OpenAI als Deprecated markiert |

Keine pauschale Freigabe für andere OpenAI-Modelle oder Audio-/Realtime-Varianten: Diese benötigen eine neue Prüfung und einen eigenen Eintrag. Anthropic, Gemini, Moonshot und Ollama verwenden bis zu ihrer eigenen belegten Implementierung weiterhin `local`.

Quellen:

- [OpenAI File Inputs](https://developers.openai.com/api/docs/guides/file-inputs) – Datei-ID, Vision-Modelle, 50-MiB-Grenze und Tokenverbrauch
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) – `responses.parse` und Pydantic-Schema
- [OpenAI Python SDK Helpers](https://github.com/openai/openai-python/blob/main/helpers.md) – `output_parsed`
- [OpenAI Data Controls](https://developers.openai.com/api/docs/guides/your-data) – Dateien bleiben bis zur Löschung gespeichert; Abuse-Monitoring kann separate Aufbewahrung haben
- [OpenAI Files Delete](https://developers.openai.com/api/reference/resources/files/methods/delete) – Löschung hochgeladener Dateien
- [LiteLLM PDF Input](https://docs.litellm.ai/docs/completion/document_understanding) – Providerübergreifender Hintergrund; der native Adapter verwendet direkt das offizielle OpenAI-SDK

### Datenschutz und Ablauf

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
- `native_pdf.py`: konservative Modellfreigabe sowie OpenAI-Upload, Responses-Parsing und Löschung
- `models.py`: Karten- und JSON-Schema sowie Deduplizierung
- `apkg.py`: Erstellung, Erweiterung und Inspektion von Anki-Paketen
- `cli.py`: ausschließlich Kommandozeilen-Workflow und Darstellung

Die Kernfunktionen akzeptieren normale Python-Objekte und sind deshalb ohne CLI aufrufbar. Eine spätere FastAPI-/Web-Schicht muss weder PDF-Verarbeitung noch Anki-Logik duplizieren.

## Qualität und Tests

Ruff prüft neben Lint und Formatierung auch Modul-, Funktions-, Methoden- und Klassen-Docstrings sowie eine zyklomatische Komplexität von höchstens 8 pro Funktion. Die Projektregeln verlangen flachen Kontrollfluss und kleine fachliche Einheiten.

```bash
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest
```

Die Tests verwenden einen simulierten KI-Client und benötigen keine API-Schlüssel. Sie prüfen unter anderem Dokumentextraktion, Kartenlimits, JSON-Validierung, APKG-Erstellung und -Erweiterung, Duplikate, Lernstand-Erhalt, Medien-Einträge und zstd-Komprimierung.

## Bewusste MVP-Grenzen und nächste sinnvolle Schritte

- Gescannte PDFs benötigen derzeit eine vorherige OCR; eingebetteter Text wird direkt gelesen.
- URLs, Bilder/Audio in Karten, Lückentext und frei wählbare Notiztypen sind noch nicht enthalten.
- KI-Ergebnisse müssen fachlich geprüft werden. Die JSON-Datei ist dafür der empfohlene Zwischenschritt.
- Bei Cloud-Providern werden Dokumentauszüge an den jeweiligen Anbieter übertragen. Für vertrauliche Dokumente ist ein lokales Modell wie Ollama vorzusehen.
- Als nächste Ausbaustufen bieten sich Quellenangaben pro Karte, eine interaktive Kartenprüfung, OCR, Cloze-Karten und ein Fortsetzen abgebrochener Generierungen an.
- Web-UI und Linux-Container/Proxmox-Deployment sind bewusst **noch nicht** Teil dieses MVP. Die Trennung von Kern und CLI bereitet beides vor, ohne jetzt Betriebskomplexität einzuführen.
