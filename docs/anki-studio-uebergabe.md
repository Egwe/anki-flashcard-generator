# Übergabe: Anki Studio

Web-Oberfläche für den Anki Flashcard Generator mit Anbindung an einen selbst betriebenen Anki-Sync-Server.

- **Stand:** 20.11.2026, Entwurf vor der Vorbereitung des Generators
- **Quelle:** Repository [Egwe/anki-flashcard-generator](https://github.com/Egwe/anki-flashcard-generator), Datei `docs/anki-studio-uebergabe.md`
- **Leser:** die Claude-Code-Session im neuen Repository „anki-studio“ und der Projektinhaber

Diese Datei ist die Ausgangslage für das neue Projekt. Sie fasst zusammen, was entschieden ist, welche Infrastruktur schon läuft und welche Schnittstellen der Generator anbietet. Fachliche Details zum Generator stehen in dessen `requirements.md`, `README.md`, `docs/benutzerhandbuch.html` und `docs/entwicklerhandbuch.html`.

> **Status des Abschnitts 11 (Schnittstellen):** Wird ausgefüllt, sobald der Generator die Anforderungen R-170 bis R-175 umgesetzt und als Version 0.2.0 getaggt hat.

---

## 1. Ziel

Anki Studio ist eine schlichte, schöne Web-Oberfläche für den Anki Flashcard Generator, betrieben im Heimnetz.

1. **Alle Funktionen der CLI im Browser:** Dokumente hochladen, Karten erzeugen, alle Optionen einstellen, Konfiguration ansehen und bearbeiten, Modelle herunterladen, JSON nach APKG exportieren, Decks ansehen.
2. **Karten landen direkt auf allen Geräten:** Anki Studio ist ein weiterer Client des eigenen Anki-Sync-Servers. Geprüfte Karten werden in die Sammlung geschrieben und synchronisiert. Danach erscheinen sie in Anki Desktop und AnkiDroid nach deren nächstem Sync.
3. **APKG bleibt als Alternative:** Statt in die Sammlung zu schreiben, kann jedes Ergebnis als APKG- oder JSON-Datei heruntergeladen werden.

### Ausdrücklich nicht Ziel

- **Lernen im Browser.** Zum Lernen gibt es Anki Desktop und AnkiDroid. Anki Studio wird kein vollständiger Anki-Client.
- **Zugriff aus dem Internet.** Nur im LAN; von unterwegs über das vorhandene NetBird-VPN.
- **Mehrere Benutzer.** Ein Benutzer, ein Login.
- **API-Schlüssel in der Oberfläche bearbeiten.** Schlüssel stehen in einer Umgebungsdatei auf dem Server (Entscheidung, siehe Abschnitt 2).

---

## 2. Getroffene Entscheidungen

| Thema | Entscheidung | Begründung |
|---|---|---|
| Basis | **Eigene Anwendung**, nicht auf [aitsc/ankiweb](https://github.com/aitsc/ankiweb) aufbauen | ankiweb hat Sync ausdrücklich ausgeschlossen, übernimmt die originale Anki-Oberfläche als kompilierte Bundles (nicht umgestaltbar), pinnt `anki==25.9.4` (Generator und Server nutzen 26.09.4) und ist AGPL-3.0. Ein Fork wäre mehr Arbeit, nicht weniger. |
| Muster aus ankiweb | Als Vorlage lesen, nicht kopieren | Brauchbar: Sammlungszugriff seriell über einen Worker mit `asyncio.Lock` (pylib ist nicht threadsicher), Passwort-Login mit Session-Cookie, Prüfung des `Host`-Headers, Zwischenablage für Uploads. Bei Übernahme von Code gilt AGPL. |
| Rolle | Anki Studio ist ein **Sync-Client** wie Desktop und AnkiDroid | Der Sync-Server ist die zentrale Datenquelle. Das offizielle `anki`-Paket enthält die Client-Sync-Funktionen. |
| Generator-Einbindung | **Python-Abhängigkeit über Git-Tag**, kein Git-Submodul | Gleich gute Versionsfestlegung, einfacheres Deployment (`uv sync`). Für gleichzeitige Entwicklung an beiden Repos eine lokale editable-Quelle per uv. |
| Backend | **FastAPI** + uvicorn | Python wie der Generator; Pydantic-Modelle des Generators direkt nutzbar. |
| Frontend | **Jinja2 + HTMX + Alpine.js + Pico CSS** | Kein Node-Build, alles in Python testbar (pytest + `TestClient`), schlichtes und sauberes Aussehen mit Dark Mode. Alle Frontend-Dateien werden mitgeliefert (kein CDN), damit es offline im LAN funktioniert. Falls Pico zu schlicht wird: Tailwind + DaisyUI über die eigenständige Tailwind-CLI. |
| Live-Fortschritt | Server-Sent Events | Der Generator meldet strukturierte Ereignisse (R-171); SSE reicht für eine Richtung und funktioniert mit dem HTMX-SSE-Plugin. |
| Lernen im Browser | **Nicht bauen** | Entscheidung des Projektinhabers. |
| Zugriff | **Nur LAN**, von außen über NetBird-VPN | Kein Reverse Proxy mit öffentlichem HTTPS nötig. Login bleibt trotzdem Pflicht, weil hinter der App API-Schlüssel und damit Kosten stehen. |
| Secrets | **Nur Umgebungsdatei** auf dem Server (`EnvironmentFile` der systemd-Unit, Rechte 0600) | Entscheidung des Projektinhabers; das Projekt richtet sich an technisch versierte Nutzer. Die Oberfläche zeigt nur „gesetzt“ oder „fehlt“. |
| Deployment | **Eigener LXC** auf Proxmox, systemd, uv; nicht im Container des Sync-Servers | Dessen Community-Update-Skript baut seine Python-Umgebung neu. Getrennte Aufgaben, getrennte Backups. |
| Name | „Anki Studio“ (Paket `anki_studio`) | „AnkiWeb“ ist der Name des offiziellen Dienstes von Ankitects. |

---

## 3. Vorhandene Infrastruktur

### 3.1 Anki-Sync-Server (läuft, getestet)

Installiert mit dem Proxmox-Community-Script [anki-sync-server](https://community-scripts.org/scripts/anki-sync-server). Desktop und AnkiDroid sind verbunden; Karten vom Desktop erscheinen auf dem Handy.

Angaben aus dem Script (Stand 20.11.2026, auf dem Server zu prüfen):

| Punkt | Wert |
|---|---|
| Basis | Debian 13, unprivilegierter LXC, 1 vCPU, 512 MB RAM, 4 GB Disk |
| Installation | `uv venv --python 3.12 /opt/anki-sync-server/venv`, darin pip-Paket `anki==<neueste GitHub-Release>` (bei Installation 26.09.4) |
| Dienst | systemd-Unit `anki-sync-server`, `ExecStart=/opt/anki-sync-server/venv/bin/python -m anki.syncserver`, läuft als root |
| Konfiguration | `/opt/anki-sync-server/.env` (0600): `SYNC_USER1=anki:<zufälliges Passwort>`, `SYNC_BASE=/opt/anki-sync-server/data`, `SYNC_HOST=0.0.0.0`, `SYNC_PORT=8080` |
| Endpunkt | `http://<IP des Sync-LXC>:8080/` (unverschlüsseltes HTTP, nur LAN/VPN) |
| Weitere Benutzer | Zusätzliche Zeilen `SYNC_USER2=name:passwort` in der `.env`, danach Dienst neu starten |
| Updates | Update-Funktion des Community-Scripts: stoppt den Dienst, sichert `.env` und `data`, installiert die neueste `anki`-Release, startet neu |

**Version beachten:** Die Server-Seite sollte nicht älter sein als die Clients. Anki Studio pinnt deshalb genau die `anki`-Version des Servers und wird bei einem Server-Update im selben Schritt angehoben.

### 3.2 Container für Anki Studio (angelegt)

- Eigener LXC auf demselben Proxmox-Host ist bereits angelegt.
- **GPU-Durchreichung ist eingerichtet:** NVIDIA Quadro K1200.
- **SSH-Zugang vom Rechner des Projektinhabers ist eingerichtet.** Die Claude-Session im Anki-Studio-Repo darf sich per SSH verbinden, den Container untersuchen und einrichten. Hostname oder Alias beim Projektinhaber erfragen oder in dessen `~/.ssh/config` nachsehen. Adressen und Zugangsdaten gehören nicht ins Repository.

Erste Bestandsaufnahme im Container (Vorschlag):

```bash
cat /etc/os-release; uname -r; nproc; free -h; df -h /
nvidia-smi                        # Treiber, CUDA-Version, Speicher
ls -l /dev/nvidia*                # durchgereichte Geräte
python3 --version; command -v uv
getent hosts <sync-lxc>; curl -sS -o /dev/null -w '%{http_code}\n' http://<sync-lxc>:8080/
```

### 3.3 Die GPU (NVIDIA Quadro K1200) – zu prüfen

Die K1200 ist eine Maxwell-Karte (GM107, Compute Capability 5.0, 4 GB GDDR5). Ob sie für den strukturierten PDF-Modus des Generators (Docling, R-158) taugt, ist offen:

- Neuere PyTorch-CUDA-Builds unterstützen ältere Architekturen teils nicht mehr. Prüfen mit `python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_arch_list())"`. `sm_50` muss in der Liste stehen, sonst einen älteren CUDA-Build von PyTorch (z. B. `cu126`) testen.
- Der Treiber im Container muss zur Version des Host-Treibers passen.
- 4 GB VRAM sind knapp, wenn Docling und das lokale Bildmodell gleichzeitig laden. Messen statt vermuten.
- **Ausweichwege, falls die Karte nicht reicht:** `pdf_mode: native` (Upload an einen freigegebenen Provider), `--allow-cpu` mit `--no-formulas` für kurze Dokumente, Bildbeschreibung über ein Profil (z. B. Ollama auf einem Rechner mit stärkerer GPU) oder `pdf_mode: local`.

Der Generator nimmt keinen stillen Moduswechsel vor (R-158); Anki Studio darf das auch nicht.

---

## 4. Architektur

```
 Browser (LAN / NetBird)
        │  HTTP, SSE
        ▼
 ┌───────────────────────── LXC „anki-studio“ ─────────────────────────┐
 │ FastAPI + Jinja2/HTMX                                               │
 │   ├─ Auth (ein Passwort, Session-Cookie, Host-Prüfung)              │
 │   ├─ Jobs (ein Worker, Job-Ordner, Ereignisse → SSE)                │
 │   │     └─ anki_flashcards (Generator-Paket, Dienst R-170..R-174)   │
 │   ├─ Sammlung (lokale Kopie, serieller Zugriff)                     │
 │   └─ Sync (sync_login, sync_collection, Schutz vor Komplett-Sync)   │
 │ /var/lib/anki-studio: collection/, jobs/, uploads/                   │
 └───────────────────────────────┬─────────────────────────────────────┘
                                 │ Anki-Sync-Protokoll (HTTP, LAN)
                                 ▼
 ┌──────────── LXC „anki-sync-server“ ────────────┐
 │ python -m anki.syncserver  :8080              │ ◄── Anki Desktop
 │ /opt/anki-sync-server/data (maßgebliche Daten) │ ◄── AnkiDroid
 └────────────────────────────────────────────────┘
```

### Ablauf einer Generierung

```
Upload → Job anlegen → Generator erzeugt Karten (local | structured | native)
       → Karten-JSON im Job-Ordner → Prüfen/Bearbeiten im Browser
       → Ziel wählen:
           a) Sammlung: Sync holen → Karten über die Anki-API hinzufügen → Sync senden
           b) Download: APKG neu erzeugen oder hochgeladene APKG erweitern; JSON-Download
```

---

## 5. Anforderungen an Anki Studio

Begriffe wie im Generator: **muss**, **soll**, **kann**. IDs mit Präfix `AS-`.

### 5.1 Oberfläche und Funktionen

**AS-001 – Generieren · muss**
Mehrere Dateien hochladen (PDF, DOCX, HTML, Markdown, Text; je höchstens 100 MiB wie im Generator). Pro Datei ein Job. Alle Optionen von `anki-flashcards generate` sind wählbar: Profil, Modell, Sprache, Limit, zusätzliche Anweisungen, Chunk-Größe, Timeout, API-Basis, PDF-Modus mit den Optionen des strukturierten Modus (Formeln, OCR erzwingen, nicht lesbare Elemente zulassen, CPU zulassen, Bild-Backend, Bild-Profil, aufbereiteten Text speichern), Unterdecks. Vorbelegung aus der YAML-Konfiguration; selten genutzte Optionen eingeklappt. Optionen des strukturierten Modus nur sichtbar, wenn dieser Modus gewählt ist.

**AS-002 – Ziel wählen · muss**
Ziel ist entweder ein Deck der synchronisierten Sammlung (Auswahl aus vorhandenen Decks oder neuer Name, `::` für Unterdecks), eine neue APKG-Datei zum Download oder eine hochgeladene APKG zum Erweitern.

**AS-003 – Datenübertragung bestätigen · muss**
Bei `pdf_mode: native` und beim Bild-Backend `profile` muss der Benutzer vor dem Start ausdrücklich bestätigen, dass das Dokument beziehungsweise Bildausschnitte an den Provider gehen. Ohne Bestätigung startet der Job nicht.

**AS-004 – Live-Fortschritt · muss**
Job-Seite mit Live-Fortschritt aus den Generator-Ereignissen: Phase, Schritte, Abschnitte, Anzahl einzigartiger Karten, Hinweise und Warnungen, Statistik der Aufbereitung. Ein Job lässt sich abbrechen (R-172 des Generators).

**AS-005 – Karten prüfen · muss**
Nach der Generierung erscheinen die Karten in einer Tabelle: Frage, Antwort, Unterdeck, Tags. Einzelne Karten lassen sich bearbeiten, löschen oder abwählen. Erst danach wird geschrieben. Bearbeitete Karten durchlaufen dieselbe Pydantic-Validierung des Generators (`Card`).

**AS-006 – Ergebnis · muss**
Nach dem Schreiben: hinzugefügte und übersprungene Karten, Aufteilung nach Unterdecks, Sync-Ergebnis. Downloads: APKG, Karten-JSON, aufbereiteter Text (falls erzeugt).

**AS-007 – Decks · muss**
Deckbaum der synchronisierten Sammlung mit Kartenanzahl. Ebenso für eine hochgeladene APKG (entspricht `anki-flashcards decks`).

**AS-008 – Export · muss**
Karten-JSON hochladen und als APKG ausgeben oder in die Sammlung schreiben (entspricht `anki-flashcards export`).

**AS-009 – Konfiguration · muss**
Wirksame Werte mit Herkunft anzeigen (entspricht `config show`). Profile und Standardwerte der YAML bearbeiten, validiert über das Schema des Generators und atomar gespeichert (`load_config`/`save_config`, R-117). API-Schlüssel erscheinen nur als „gesetzt“ oder „fehlt“.

**AS-010 – Modelle · muss**
Docling- und Bildmodelle herunterladen (entspricht `models download`), mit Fortschritt; anzeigen, ob eine GPU erkannt wird.

**AS-011 – Sync-Status · muss**
Seite mit Endpunkt, angemeldetem Benutzer, Zeitpunkt und Ergebnis des letzten Syncs, Knopf „Jetzt synchronisieren“.

**AS-012 – Gestaltung · muss**
Schlicht und aufgeräumt, gut lesbar, Dark Mode, auf Desktop und Handy bedienbar. Keine externen Ressourcen zur Laufzeit.

**AS-013 – Karten in der Sammlung durchsuchen und bearbeiten · kann · später**
Suche über `col.find_notes`, Bearbeiten und Löschen generierter Notizen.

### 5.2 Sync

**AS-020 – Anmeldung · muss**
Endpunkt in der Konfiguration von Anki Studio, Benutzername und Passwort in der Umgebungsdatei. Anmeldung über `Collection.sync_login(username, password, endpoint)`; das Ergebnis (`SyncAuth` mit `hkey` und `endpoint`) wird verwendet, das Passwort nicht weiter gespeichert oder angezeigt.

**AS-021 – Erster Abgleich · muss**
Ist die lokale Kopie leer, verlangt der Server einen Komplett-Sync. Anki Studio lädt dann die Sammlung **herunter** (`close_for_full_sync()`, dann `full_upload_or_download(auth=…, server_usn=…, upload=False)`, dann neu öffnen).

**AS-022 – Normaler Sync · muss**
Vor jedem Schreiben in die Sammlung und danach ein schrittweiser Sync über `sync_collection(auth, sync_media=False)`. Ergebnis `required` aus `SyncCollectionResponse.ChangesRequired`: `NO_CHANGES`, `NORMAL_SYNC`, `FULL_SYNC`, `FULL_DOWNLOAD`, `FULL_UPLOAD`. Liefert der Server `new_endpoint`, wird dieser übernommen.

**AS-023 – Kein automatischer Komplett-Upload · muss**
Ein Komplett-Upload überschreibt die Daten auf dem Server und damit auf allen Geräten. Er findet niemals automatisch statt. Verlangt der Server einen Komplett-Sync, während die lokale Kopie eigene, noch nicht gesendete Änderungen hat, bricht Anki Studio ab und erklärt die Lage. Ein Komplett-Download ist nur erlaubt, wenn lokal nichts verloren geht.

**AS-024 – Nicht in die Server-Daten schreiben · muss**
Anki Studio schreibt nie direkt in `/opt/anki-sync-server/data` oder eine andere Server-Datei. Das umgeht die Sync-Buchhaltung und beschädigt die Synchronisierung.

**AS-025 – Serieller Zugriff · muss**
Die pylib-Sammlung ist nicht threadsicher. Alle Zugriffe auf die Sammlung laufen nacheinander über einen Worker. Generierung (KI, Docling) läuft außerhalb dieser Sperre.

**AS-026 – Medien · kann · später**
Medien-Sync (`sync_media`) erst, wenn Karten Bilder oder Audio enthalten (R-205 des Generators).

### 5.3 Betrieb und Sicherheit

**AS-030 – Login · muss**
Ein Passwort; nur sein Hash steht in der Umgebungsdatei. Session-Cookie `HttpOnly`, `SameSite=Strict`. Prüfung des `Host`-Headers gegen eine Liste erlaubter Namen.

**AS-031 – Secrets · muss**
API-Schlüssel der Provider, Sync-Zugangsdaten und Login-Hash nur in der Umgebungsdatei. Die YAML enthält wie im Generator nur Variablennamen (`api_key_env`). Keine Secrets in Logs, Job-Dateien, Fehlermeldungen oder der Oberfläche.

**AS-032 – Jobs · muss**
Ein Job läuft zur Zeit (eine GPU, ein Benutzer); weitere warten in einer Warteschlange. Jeder Job hat einen Ordner mit Upload, Ereignisprotokoll, Karten-JSON und Ergebnis. Nach einem Neustart sind abgeschlossene Jobs weiter sichtbar; laufende gelten als abgebrochen. Alte Jobs werden nach einer einstellbaren Frist gelöscht.

**AS-033 – Uploads · muss**
Größengrenze vor dem Speichern prüfen, Dateinamen nie ungeprüft als Pfad verwenden, Uploads nur im Job-Ordner ablegen.

**AS-034 – Tests · muss**
Reguläre Tests laufen ohne Netzwerk, ohne Sync-Server, ohne API-Schlüssel und ohne GPU. KI-Aufrufe werden wie im Generator simuliert; für Sync-Tests eine temporäre Sammlung und ein simulierter oder lokal gestarteter `anki.syncserver` mit Testbenutzer.

### 5.4 Deployment (R-201 des Generators)

**AS-040 – Installation · muss**
Im LXC „anki-studio“: eigener Systembenutzer statt root; Programm mit uv in `/opt/anki-studio`; Daten in `/var/lib/anki-studio`; Konfiguration `/etc/anki-studio/config.yaml` (Generator-YAML) und `/etc/anki-studio/studio.yaml` (Endpunkt, Datenpfade, Port); Secrets in `/etc/anki-studio/env` (0600) als `EnvironmentFile`; systemd-Unit mit uvicorn. Ein Installations- und Update-Skript im Repo (`deploy/`).

**AS-041 – GPU · soll**
Strukturierter Modus mit der durchgereichten GPU, sofern Abschnitt 3.3 sie als nutzbar bestätigt. Sonst dokumentieren, welche Ausweichwege gelten.

**AS-042 – Backup · soll**
vzdump beider Container. Maßgeblich sind die Daten des Sync-Servers; die Sammlung von Anki Studio ist eine Kopie und lässt sich neu herunterladen.

**AS-043 – Community-Script · kann · später**
Daraus ein eigenes Proxmox-Community-Script (`ct/` + `install/`) machen.

---

## 6. Repository-Aufbau (Vorschlag)

```
anki-studio/
  pyproject.toml           # fastapi, uvicorn, jinja2, python-multipart, sse-starlette o. ä.,
                           # anki==<Server-Version>,
                           # anki-flashcard-generator @ git+https://github.com/Egwe/anki-flashcard-generator@v0.2.0
  src/anki_studio/
    app.py                 # App-Factory, Middleware (Auth, Host-Prüfung)
    auth.py
    settings.py            # Einstellungen von Anki Studio (Pfade, Endpunkt, Port)
    jobs.py                # Warteschlange, Worker-Thread, Job-Ordner, Ereignisse
    collection.py          # lokale Sammlung, serieller Zugriff
    sync.py                # Login, Sync, Schutz vor Komplett-Upload
    routes/                # generate, review, decks, export, config, models, sync
    templates/  static/    # htmx, alpine, pico: mitgeliefert, kein CDN
  deploy/                  # systemd-Unit, install.sh, update.sh, env.example
  tests/
  AGENTS.md  README.md  requirements.md
```

Einbindung des Generators während der Entwicklung (Nachbar-Checkout):

```toml
[tool.uv.sources]
anki-flashcard-generator = { path = "../anki-flashcard-generator", editable = true }
```

Für das Deployment den Git-Tag verwenden. Ist das GitHub-Repository privat, braucht der Container einen Deploy-Key oder ein Token mit Lesezugriff.

Arbeitsweise: Die Regeln aus `AGENTS.md` des Generators (Branch je Anforderungspaket, kleine Commits, Docstrings an jeder Funktion, Never Nesting, Ruff, pytest, ehrlicher Requirement-Status) sollten in ein eigenes `AGENTS.md` von Anki Studio übernommen werden.

---

## 7. Vorgehen

| Phase | Inhalt | Ort |
|---|---|---|
| 0 | **Sync-Prototyp** gegen einen Testbenutzer: `SYNC_USER2=test:…` auf dem Sync-Server anlegen; per Skript anmelden, komplett herunterladen, eine APKG des Generators beziehungsweise Karten über dessen Sammlungs-Schnittstelle hinzufügen, synchronisieren, in AnkiDroid prüfen. Die echte Sammlung bleibt unberührt. Dabei klären: Löst der erste Import des Notiztyps „KI Karteikarte (Front/Back)“ einen Komplett-Sync aus? | Wegwerf-Skript |
| 0b | **Container-Bestandsaufnahme** per SSH (Abschnitt 3.2) und GPU-Test (Abschnitt 3.3) | Container |
| 1 | Vorbereitung des Generators: R-170 bis R-176, Tag `v0.2.0` | Generator-Repo (erledigt, wenn Abschnitt 11 ausgefüllt ist) |
| 2 | Web-MVP: Login, Generieren, Live-Fortschritt, Prüfen, APKG- und JSON-Download | anki-studio |
| 3 | Sync: Anmeldung, lokale Sammlung, Deckauswahl, Schreiben und Synchronisieren | anki-studio |
| 4 | Deployment im LXC: systemd, uv, Pfade, Backup | anki-studio |
| 5 | Optional: Karten durchsuchen und bearbeiten (AS-013) | anki-studio |

---

## 8. Risiken und offene Punkte

| Punkt | Umgang |
|---|---|
| GPU K1200 mit aktuellem PyTorch | Abschnitt 3.3; Ergebnis dokumentieren |
| Erster Import des Notiztyps erzwingt eventuell einen Komplett-Sync | In Phase 0 mit dem Testbenutzer prüfen. Notfalls den Notiztyp einmalig am Desktop anlegen (APKG importieren und synchronisieren). |
| Versionsabstand `anki` Server ↔ Anki Studio | Gleiche Version pinnen; Updates gemeinsam |
| Stabile GUIDs des Generators (`genanki.guid_for(deck, frage)`) | Wird eine generierte Notiz in ein anderes Deck verschoben und dieselbe Frage erneut erzeugt, entsteht eine zweite Notiz mit gleicher GUID. Für Sync unkritisch (Sync nutzt Notiz-IDs); bei späteren APKG-Importen zu beachten. |
| Lizenz | Das `anki`-Paket ist AGPL-3.0. Für den privaten Betrieb unkritisch; vor einer Veröffentlichung von Anki Studio klären. |
| Unverschlüsseltes HTTP zum Sync-Server | Nur LAN beziehungsweise NetBird; nicht ins Internet öffnen. |

---

## 9. Was im Generator bereits vorhanden ist

Für Anki Studio direkt nutzbar (Stand 0.1.0):

| Bereich | Modul | Nutzen |
|---|---|---|
| Konfiguration | `anki_flashcards.config`: `AppConfig`, `load_config`, `save_config` | YAML-Schema mit strenger Validierung, atomares Speichern (R-117) |
| Einstellungen | `anki_flashcards.settings`: `load_selected_config`, `resolve_generate_settings`, `resolve_export_settings`, `configuration_diagnostics` | Priorität Default → YAML/Profil → expliziter Wert; Diagnose ohne Secrets |
| Karten | `anki_flashcards.models`: `Card`, `save_cards`, `load_cards`, `deduplicate_cards` | Validierung und versioniertes Karten-JSON |
| APKG | `anki_flashcards.apkg`: `create_apkg`, `append_apkg`, `inspect_apkg`, `read_subdeck_context` | Pakete erzeugen, erweitern, lesen |
| Fehler | `anki_flashcards.errors.FlashcardError` | Verständliche Anwendungsfehler |

Was bis 0.1.0 fehlt und mit 0.2.0 kommt: der Ablauf selbst (bisher in `cli.py` mit Konsolenausgabe verflochten), strukturierte Ereignisse, Abbruch, getrenntes Erzeugen und Schreiben, Sammlung als Ziel.

---

## 10. Hinweise für Werte aus der Oberfläche

`resolve_generate_settings` erwartet ein Mapping mit nur den ausdrücklich gesetzten Werten (fehlende Schlüssel bedeuten „aus YAML oder Default“). Die Oberfläche übergibt Formularwerte genauso: leere Felder weglassen, nicht als `None` setzen. In der Herkunftsanzeige erscheinen solche Werte als `cli`; gemeint ist „explizit vom Aufrufer“.

---

## 11. Schnittstellen des Generators ab 0.2.0

*Wird nach Umsetzung von R-170 bis R-175 ausgefüllt.*
