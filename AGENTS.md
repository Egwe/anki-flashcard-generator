# Arbeitsregeln für Agents – Anki Flashcard Generator

## 1. Geltung und Informationsquellen

Diese Regeln gelten für das gesamte Repository und für menschliche wie automatisierte Mitwirkende.

- [requirements.md](./requirements.md) ist die verbindliche, konsolidierte Fach- und Technikspezifikation.
- [req.md](./req.md), [req-2.md](./req-2.md) und [req-3.md](./req-3.md) sind die unveränderten Originalvorgaben.
- [README.md](./README.md) beschreibt den aktuell nutzbaren Stand und konkrete Bedienung.
- [docs/entwicklerhandbuch.html](./docs/entwicklerhandbuch.html) erklärt Architektur, Module, Abläufe, Datenformate, Test-Nahtstellen und Erweiterungspunkte des aktuellen Codes.
- Diese Datei beschreibt **wie** gearbeitet wird, nicht den behaupteten Implementierungsstand.

Bei Konflikten zwischen bereits implementiertem Verhalten und den Anforderungen wird das Verhalten nicht stillschweigend geändert: Zuerst Anforderung, Auswirkung und gewünschten Status klären, dann Code, Tests und Dokumentation gemeinsam aktualisieren. Neue Anforderungen sind „offen“, bis sie implementiert und validiert sind.

## 2. Grundprinzipien

1. **Kleine, überprüfbare Lösungen:** Kernfunktionen einfach halten und keine vorzeitige Web-, Container- oder Provider-Infrastruktur bauen.
2. **Unix-Philosophie:** Module und Funktionen erfüllen eine klar benannte Aufgabe und lassen sich unabhängig testen und kombinieren.
3. **Trennung der Belange:** Dokumentverarbeitung, KI-Generierung, Konfiguration, Anki-Persistenz und CLI-Darstellung bleiben getrennt.
4. **Keine Funktionsbehauptungen ohne Beleg:** Dokumentation, Tests oder ausgeführte Befehle müssen den gemeldeten Stand stützen.
5. **Keine ungefragten Zusatzänderungen:** Keine unverbundenen Refactorings, Dependency-Upgrades oder Formatänderungen. Eng mit der Änderung verbundene Fehler werden behoben und begründet.

## 3. Arbeitsablauf, Branches und Commits

### Verbindlicher Branch-Workflow

Alle offenen **Muss- und Soll-Anforderungen** werden schrittweise abgearbeitet. **Kann-Anforderungen** sind keine impliziten Implementierungsaufträge.

Für jede Gruppe inhaltlich zusammengehöriger Requirements gilt dieser vollständige Zyklus:

1. Auf aktuellem, sauberem `main` einen beschreibenden Feature-Branch erstellen, beispielsweise `feature/cli-help`, `feature/config-services` oder `feature/native-pdf-openai`.
2. Betroffene Requirement-IDs bestimmen und bestehenden Code, Tests, Dokumentation sowie tatsächliches Verhalten prüfen.
3. Ein kleines, abgegrenztes Paket bearbeiten, beispielsweise:
   - CLI-Hilfe,
   - Docstring-/Never-Nesting-Refactoring eines Moduls,
   - YAML-Schema und Laden,
   - Konfigurationszusammenführung,
   - ein geprüfter Native-PDF-Adapter.
4. Zuerst fokussierte Tests ausführen und danach alle relevanten Qualitätsprüfungen.
5. Direkt betroffene Dokumentation und Requirement-Status im selben Paket aktualisieren.
6. Änderungen und Git-Diff prüfen und **einen eigenen kleinen Commit** erstellen. Größere Pakete dürfen mehrere fachlich geschlossene Zwischencommits erhalten.
7. Erst wenn alle vorgesehenen Prüfungen erfolgreich sind, auf `main` wechseln und den Feature-Branch mit einem nachvollziehbaren Merge-Commit integrieren. Kein Merge bei roten Tests.
8. Den gemergten Stand auf `main` prüfen. Erst danach mit dem nächsten inhaltlich zusammengehörigen Anforderungspaket und einem neuen Branch beginnen.

Nicht mehrere unabhängige Requirements bis zu einem großen Schluss-Commit aufstauen. Ein Commit enthält nur zusammengehörige, getestete Änderungen. Ein späteres Paket darf auf einem validierten vorherigen Paket aufbauen. Nach erfolgreichem Merge kann der lokale Feature-Branch gelöscht werden; der Merge-Verlauf bleibt im Repository nachvollziehbar. Vor einem Branchwechsel muss das Arbeitsverzeichnis sauber sein oder die aktuelle Arbeit anderweitig ausdrücklich gesichert werden.

### Git-Regeln

- Keine Dateien aus dem Arbeitsverzeichnis des Nutzers verwerfen, überschreiben oder zurücksetzen.
- Keine destruktiven Git-Befehle oder History-Rewrites ohne ausdrücklichen Auftrag.
- Keine Secrets, lokalen Konfigurationen, virtuellen Umgebungen, Caches oder erzeugten APKG-/Karten-JSON-Dateien committen.
- Commit-Nachrichten beschreiben das abgeschlossene Anforderungspaket und verwenden bei Agent-Commits den vorgesehenen Co-authored-by-Trailer.
- Der Commit ersetzt nicht den Abschlussbericht mit getestetem Verhalten und ausgeführten Prüfungen.

## 4. Python- und Coderegeln

### Never Nesting

Für jede neue oder geänderte Funktion gilt:

- Guard Clauses und frühe Rückgaben statt tiefer `if`-Pyramiden.
- Kleine, fachlich benannte Funktionen statt verschachtelter Schleifen mit mehreren Entscheidungsebenen.
- Tabellen, Enums oder Strategieobjekte für echte Varianten statt langer `if`/`elif`-Ketten, sofern dies die Lesbarkeit verbessert.
- Keine Komplexität lediglich in anonyme Funktionen oder unklare Helfer verschieben.
- Keine breiten `except Exception`-Blöcke als Kontrollfluss; nur an einer echten System-/Bibliotheksgrenze abfangen und in eine verständliche Anwendungsfehlermeldung übersetzen.
- Kontextmanager und `try`-Blöcke klein halten; natürliche syntaktische Blöcke nicht durch schwerer lesbare Konstrukte ersetzen.

Bestandscode wird schrittweise und mit Regressionstests verbessert. Ein reines Struktur-Refactoring darf das externe Verhalten nicht ändern.

### Dokumentation von Funktionen und Klassen

Jede benannte Funktion, Methode und Klasse – auch privat und in Tests – erhält einen konkreten Docstring. Er dokumentiert:

- Zweck und Verhalten,
- alle Parameter inklusive Einheiten oder Grenzen, sofern relevant,
- Rückgabewert und Datenform,
- relevante Exceptions und Seiteneffekte wie Datei-, Netzwerk- oder Datenbankzugriffe.

Beispiel:

```python
def chunk_text(text: str, max_chars: int = 24_000, overlap: int = 500) -> list[str]:
    """Split source text into overlapping chunks for model requests.

    Args:
        text: Normalized source text.
        max_chars: Maximum characters per chunk; at least 1,000.
        overlap: Repeated characters between adjacent chunks.

    Returns:
        Non-empty chunks covering the complete source text.

    Raises:
        ValueError: If chunk size or overlap is invalid.
    """
```

Bei Klassen werden wesentliche Attribute beziehungsweise Konstruktorparameter dokumentiert. Funktionen ohne Parameter wiederholen nicht „keine Parameter“. Funktionen mit dem Hauptzweck eines Seiteneffekts geben `None` im Docstring an. Docstrings beschreiben beobachtbares Verhalten, nicht den Quelltext Satz für Satz. Typannotationen bleiben erforderlich, soweit sie für den jeweiligen Code sinnvoll bestimmbar sind.

Triviale anonyme Ein-Zeilen-Schlüssel sind zulässig. Fachliche Logik gehört in benannte, dokumentierte Funktionen.

### Weitere Regeln

- Vorhandene Formatierung und Tooling verwenden; Python-Zielversion ist 3.11+.
- Öffentliche und fachliche Schnittstellen typisieren; dynamische Bibliotheksgrenzen gezielt kapseln.
- Keine toten Kommentare oder kommentierten alten Code.
- Kommentare nur für nicht offensichtliche Gründe und Annahmen; Dokumentation gehört in Docstrings beziehungsweise Markdown.
- Abhängigkeiten nur ergänzen, wenn sie die Anforderung benötigt, und anschließend die Manifestdatei sowie Dokumentation aktualisieren.
- CLI-Framework-Objekte und Konsolenausgaben gehören nicht in fachliche Kernservices.

## 5. Konfiguration und KI-Provider

### Konfiguration

- Zentrales Format gemäß Anforderung ist YAML mit `schema_version` und strenger Validierung.
- Die Beispieldatei enthält erklärte Modellbausteine, aber keine echten Zugangsdaten.
- API-Schlüssel werden ausschließlich aus der Umgebung gelesen; YAML darf nur den Variablennamen enthalten.
- Die Priorität ist zwingend: eingebauter Default → YAML/Profil → ausdrücklicher CLI-Wert. `.env` und Umgebungsvariablen liefern ausschließlich Zugangsdaten für `api_key_env`; sie dürfen Modelle, Endpunkte oder Generierungsparameter nicht überschreiben. `ANKI_CONFIG` wählt nur den YAML-Dateipfad. Die Altvariablen `ANKI_MODEL` und `LLM_API_BASE` werden nicht unterstützt.
- config.example.yaml muss jedes Profilfeld und die offiziellen Standardendpunkte der unterstützten Beispielprovider dokumentieren. .env.example enthält nur Credential-Platzhalter und die optionale YAML-Pfadwahl, keine Modelle oder Endpunkte.
- Boolesche CLI-Optionen benötigen positive und negative Form, damit YAML-Werte in beiden Richtungen überschrieben werden können.
- CLI-Pfade und YAML-Pfade werden nach [requirements.md](./requirements.md) unterschiedlich aufgelöst.
- Laden, Validieren, Zusammenführen und atomares Speichern müssen ohne CLI beziehungsweise Web-UI nutzbar sein.
- Diagnoseausgaben enthalten keine Secrets und keine unmaskierten sensitiven Verbindungsdaten.

### KI und native PDF-Verarbeitung

- Modelle werden über `provider/modell` angesprochen; der generative Kern bleibt providerunabhängig.
- Jede KI-Antwort durchläuft dieselbe Pydantic-Validierung und Duplikaterkennung.
- Kein Modell und keine Provider-Fähigkeit anhand des Namens vermuten.
- Vor nativem Datei-Upload aktuelle offizielle Provider-/LiteLLM-Dokumentation prüfen und Quelle, Prüfdatum, Modellgrenzen sowie unterstützte Fähigkeiten dokumentieren.
- Lokale Extraktion bleibt Standard. Native Verarbeitung erfordert `pdf_mode: native` beziehungsweise den entsprechenden CLI-Wert und einen geprüften Adapter.
- Nicht unterstützte Fähigkeiten sind ein verständlicher Fehler, kein stiller Fallback und kein stiller Wechsel zu einem anderen Modell.
- Der Native-Pfad darf die lokale PDF-Extraktion nicht aufrufen und muss dieselbe Kartenvalidierung und APKG-Ausgabe verwenden.
- Dokumente und Originaldateien niemals unbemerkt an Dritte übertragen. Upload-Lebenszyklus, Grenzen und Datenschutz dokumentieren.

## 6. Anki- und Dateisicherheit

- Neue APKG-Pakete werden mit `genanki` erzeugt; Erweiterungen erfolgen über die offizielle Anki-API, nicht durch frei konstruierte Schema-Inserts.
- Bestehende Karten, Notizen, Decks, Lernstände und andere Paket-Einträge bleiben erhalten.
- Vorhandene Ausgabedateien werden ohne ausdrückliches Extend-Verhalten nicht überschrieben.
- APKG- und JSON-Zieldateien werden über temporäre Dateien und atomares Ersetzen geschrieben.
- SQLite-WAL-Daten müssen vor dem erneuten Verpacken in die Hauptdatenbank übernommen werden.
- Klassische und zstd-komprimierte Sammlungen bleiben nach der Änderung in ihrem jeweiligen Format lesbar.
- Kartentext wird als Klartext behandelt und HTML-escaped. Duplikatvergleiche normalisieren Text ohne HTML-Seiteneffekte.
- Das Programm bearbeitet nur die angegebene APKG-Datei, niemals unbemerkt die persönliche Anki-Sammlung.

## 7. Tests und Validierung

### Testregeln

- Jede neue oder geänderte Verhalten erhält fokussierte Tests, die ohne die Änderung fehlschlagen würden.
- Erfolgsfall, relevante Grenzen, Fehlerfälle und Regressionen prüfen; keine Tests nur zur Erhöhung einer Prozentzahl.
- Bei Bugfixes zuerst eine Reproduktion oder einen fehlschlagenden Test erstellen, sofern praktikabel.
- Bestehende Verhalten bleibt durch die vorhandene Suite abgesichert. Reine Refactorings benötigen keine redundanten neuen Tests, müssen aber die bestehende Suite bestehen.
- KI-Clients und Datei-Uploads in regulären Tests simulieren. Keine echten API-Schlüssel, kostenpflichtigen Requests oder externen Uploads im Standardtestlauf.
- Temporäre Dateien und lokale Testserver nach Verwendung aufräumen beziehungsweise beenden.

### Mindestens auszuführen

Nach Codeänderungen in der projekteigenen virtuellen Umgebung:

```bash
.venv/bin/python -m ruff check src tests
.venv/bin/python -m ruff format --check src tests
.venv/bin/python -m pytest
```

Während der Entwicklung zuerst die betroffenen Tests auswählen. Bei Formatierungsänderungen Ruff-Formatierung verwenden und danach die Prüfungen erneut ausführen. Zusätzlich betroffene CLI-Aufrufe oder Integrationstests ausführen, wenn die Unit-Tests den tatsächlichen Ablauf nicht abdecken.

Reine Markdown-Änderungen benötigen keine Python-Tests. Git-Diff und Dokumentationskonsistenz sind trotzdem zu prüfen.

## 8. Dokumentation und Abschluss

- Neue Funktionen werden erst nach Implementierung und Validierung als „umgesetzt“ markiert.
- README enthält eine kompakte Übersicht über Installation, Bedienung, Defaults, Beispiele und bekannte Grenzen des aktuellen Stands. Die README ist nicht das ausführliche Benutzerhandbuch.
- [docs/benutzerhandbuch.html](./docs/benutzerhandbuch.html) ist das ausführliche, benutzerfreundliche Referenzhandbuch für alle Befehle, Argumente, Optionen und typischen Anwendungsfälle. Es bleibt ohne Build-Schritt direkt im Browser nutzbar.
- **Bei jeder Änderung des Benutzerverhaltens müssen README und docs/benutzerhandbuch.html im selben Anforderungspaket angepasst werden.** Das gilt insbesondere für neue oder geänderte Befehle, Argumente, Optionen, Defaults, Pfade, Provider-Fähigkeiten, Konfiguration, Fehlerverhalten und künftige GUI-Funktionen. Neue GUI-Bereiche benötigen dort eine eigene verständliche Bedienungsanleitung.
- Vor dem Abschluss einer solchen Änderung muss das HTML-Handbuch gegen die tatsächliche CLI-Hilfe beziehungsweise die tatsächliche GUI geprüft werden. Suchfunktion, Links, aufklappbare Bereiche und Kopierfunktionen müssen weiterhin funktionieren; das Handbuch darf keine externen Ressourcen voraussetzen.
- [docs/entwicklerhandbuch.html](./docs/entwicklerhandbuch.html) ist das technische Gegenstück für Mitwirkende. **Bei Änderungen an Modulen, öffentlichen Funktionen, Abläufen, Datenformaten, Fehlerbehandlung, Test-Nahtstellen oder Erweiterungspunkten wird es im selben Anforderungspaket angepasst**, einschließlich betroffener Diagramme. Behobene Einträge unter „Randfälle und bekannte Abweichungen“ werden dort entfernt. Für Suche, Modulfilter, Links, Kopierfunktionen und den Verzicht auf externe Ressourcen gelten dieselben Regeln wie für das Benutzerhandbuch.
- CLI-Hilfe wird aus den echten Optionen erzeugt und erklärt Pflichtparameter, Kurz-/Langformen, Defaults, Wertebereiche, Beispiele und Dateibehandlung.
- requirements.md erhält stabile Requirement-IDs und einen ehrlichen Status; Originalanforderungen werden nicht überschrieben.
- Keine zusätzlichen Planungs- oder Notizdateien anlegen, wenn die Information in requirements.md, README.md oder dieser Datei gehört.
- Abschlussmeldungen enthalten kurz: umgesetzte Requirement-IDs, geänderte wesentliche Dateien, tatsächlich ausgeführte Prüfungen und verbleibende Einschränkungen.
- Keine externe Veröffentlichung oder ein Push ohne ausdrücklichen Auftrag.
