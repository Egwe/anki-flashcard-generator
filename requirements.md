# Anforderungen – Anki Flashcard Generator

## 1. Zweck und Geltung

Dieses Dokument bündelt alle fachlichen und technischen Anforderungen aus [req.md](./req.md), [req-2.md](./req-2.md) und [req-3.md](./req-3.md). Es ergänzt die Entscheidungen und Funktionen, die bereits beim ersten MVP entstanden sind. Die drei Ausgangsdateien bleiben als Originalvorgaben erhalten; dieses Dokument ist die konsolidierte Arbeitsgrundlage.

Die Begriffe **muss**, **soll** und **kann** sind verbindlich zu unterscheiden:

- **muss**: notwendige Anforderung; Abweichungen müssen ausdrücklich entschieden und dokumentiert werden.
- **soll**: verbindlicher Standard, sofern keine begründete technische Ausnahme dokumentiert ist.
- **kann**: sinnvolle spätere Erweiterung, aber noch kein Auftrag zur Umsetzung.

### Statuslegende

- **Umgesetzt**: im aktuellen MVP vorhanden und durch Tests oder einen ausgeführten CLI-Lauf belegt.
- **Offen**: angefordert, aber noch nicht oder nur teilweise umgesetzt.
- **Später**: bewusst zurückgestellt; Architekturentscheidungen dürfen dies nicht unnötig erschweren.

Der Status bezieht sich auf den Programmcode, nicht darauf, dass eine Anforderung in diesem Dokument beschrieben ist.

## 2. Produktziel und Abgrenzung

**R-001 – Kernzweck · muss · umgesetzt**
Das Programm muss aus einem lokalen, textbasierten Dokument mithilfe eines KI-Modells Anki-Karteikarten erzeugen. Das primäre Ergebnis ist eine direkt in Anki importierbare `.apkg`-Datei.

**R-002 – Bedienung · muss · umgesetzt, Hilfe auszubauen**
Das Produkt ist zunächst ein kommandozeilenbasiertes Werkzeug. Die Kernfunktionen müssen unabhängig von der Kommandozeile aufrufbar bleiben, damit später eine Webanwendung oder ein Container denselben Kern verwenden kann.

**R-003 – Technologie · soll · umgesetzt**
Python ist die gewählte Implementierungssprache. Ausschlaggebend sind die verfügbaren Bibliotheken für Dokumentverarbeitung, KI-Provider und Anki. Die unterstützte Python-Mindestversion ist 3.11.

**R-004 – Fokus · muss · umgesetzt**
Die Anwendung bleibt zunächst bewusst schlank. Fachliche Kernfunktionen, Provider-Anbindung, APKG-Verarbeitung und CLI-Darstellung müssen getrennt bleiben. Web-UI und Proxmox-/Container-Betrieb werden vorbereitet, aber nicht vorzeitig implementiert.

## 3. Dokumenteneingabe und Textverarbeitung

**R-010 – Lokale Dateien · muss · umgesetzt**
Als Eingabe dient der Pfad zu einer lokalen Datei. URLs und das Abrufen entfernter Inhalte sind nicht Teil des MVP. Eingabedateien müssen lesbar sein und dürfen höchstens 100 MiB groß sein.

**R-011 – Dateiformate · muss · umgesetzt**
Neben PDF müssen gängige lokale Textformate unterstützt werden. Aktuell sind dies:

- PDF mit eingebettetem Text (`.pdf`),
- Word DOCX (`.docx`), einschließlich Absätzen und Tabellen,
- HTML (`.html`, `.htm`) ohne Script-, Style- und Template-Inhalte,
- Markdown (`.md`, `.markdown`),
- UTF-8-Text (`.txt`), optional mit BOM.

Nicht unterstützte Endungen, beschädigte Dokumente und Dokumente ohne extrahierbaren Text müssen mit einer verständlichen Fehlermeldung abgelehnt werden.

**R-012 – Textaufteilung · muss · umgesetzt**
Langer extrahierter Text muss für Modellaufrufe in überlappende Abschnitte aufgeteilt werden. Standard sind 24.000 Zeichen pro Abschnitt und 500 Zeichen Überlappung. Die CLI erlaubt Abschnittsgrößen von 1.000 bis 100.000 Zeichen. Absätze und Wortgrenzen sollen bevorzugt werden; jeder Quelltext muss trotz Überschneidungen vollständig berücksichtigt werden.

**R-013 – OCR · kann · später**
Gescannte PDFs ohne Textebene benötigen derzeit eine externe OCR. Eine eingebaute OCR kann später ergänzt werden.

**R-014 – Native Dokumentverarbeitung · muss · offen, siehe R-120 bis R-123**
Die lokale Extraktion muss für geeignete Modelle optional durch die native Verarbeitung der Originaldatei beim Provider ersetzt werden können.

## 4. KI-Modelle und Karteikartengenerierung

**R-020 – Provider-Unabhängigkeit · muss · umgesetzt**
Gängige KI-Anbieter müssen über eine gemeinsame Schnittstelle ansprechbar sein. LiteLLM bildet diese Schnittstelle; Modelle werden in der Form `provider/modell` angegeben. Vorgesehen und dokumentiert sind insbesondere OpenAI, Anthropic, Google Gemini, Moonshot/Kimi und Ollama. Weitere von LiteLLM unterstützte Provider sollen ohne eigene CLI-Befehle nutzbar sein.

**R-021 – Provider-Parameter · muss · umgesetzt, Konfiguration offen**
Modell, API-Endpunkt, Timeout und API-Schlüssel müssen konfigurierbar sein. Aktuell erfolgt dies über CLI-Optionen, `.env` beziehungsweise Umgebungsvariablen. Eine zentrale Modellkonfiguration wird zusätzlich gemäß R-110 bis R-119 eingeführt.

**R-022 – Geheimnisse · muss · umgesetzt und dauerhaft einzuhalten**
API-Schlüssel dürfen niemals ins Repository, in APKG-Dateien, in Karten-JSON oder in Logs geschrieben werden. Konfigurationsdateien dürfen später nur den **Namen** einer Umgebungsvariablen referenzieren, nicht deren geheimen Wert.

**R-023 – Karteninhalt · muss · umgesetzt**
Die KI muss ausschließlich fachlich durch die Quelle gedeckte, eigenständig verständliche und nicht doppelt formulierte Karten erstellen. Jede Karte besitzt eine Vorderseite (`front`), eine Rückseite (`back`) und optional Tags (`tags`). Standard ist eine einfache Frage-Antwort-Karte; Metafragen über das Dokument und erfundene Fakten sind unzulässig.

**R-024 – Strukturierte Antwort · muss · umgesetzt**
Die KI-Antwort muss als JSON mit einem `cards`-Array angefordert und mit Pydantic validiert werden. Leere Antworten, ungültiges JSON, ungültige Felder oder fehlende Pflichtinhalte müssen als verständlicher Anwendungsfehler behandelt werden. Vorderseiten sind auf 2.000, Rückseiten auf 20.000 Zeichen begrenzt. Tags enthalten keine Leerzeichen; pro Karte sind höchstens 20 Tags zulässig.

**R-025 – Parameter · muss · umgesetzt**
Folgende Generierungsparameter müssen steuerbar sein:

- Modell,
- Kartenlimit,
- Sprache, standardmäßig Deutsch,
- zusätzliche Anweisungen,
- Abschnittsgröße,
- API-Endpunkt und Timeout.

**R-026 – Kartenlimit · muss · umgesetzt**
Das Standardlimit beträgt 50 Karten. Das Programm darf nicht mehr als das angeforderte Limit exportieren. `--limit 0` aktiviert den ausdrücklich gewählten Unlimited-Modus: Jeder Textabschnitt wird einmal verarbeitet und die KI soll so viele sinnvolle Karten erzeugen, wie die Quelle hergibt. Das Unlimited-Verhalten muss dokumentiert bleiben; standardmäßig ist ein Limit zu verwenden.

**R-027 – Provider-Fehler · muss · umgesetzt**
Anfragen verwenden einen Timeout von standardmäßig 180 Sekunden und bis zu zwei Wiederholversuche durch LiteLLM. Fehler müssen mit dem betroffenen Dokumentabschnitt gemeldet werden. Nicht jedes Modell unterstützt jede strukturierte Ausgabe gleichermaßen; solche Einschränkungen dürfen nicht als erfolgreiche Generierung ausgegeben werden.

**R-028 – Datenschutz · muss · umgesetzt, für Direkt-Upload zu erweitern**
Bei Cloud-Providern werden verarbeitete Dokumentauszüge an den Anbieter übertragen. Dies muss dokumentiert sein. Für vertrauliche Dokumente soll ein lokales Modell verwendet werden. Ein späterer Datei-Upload muss noch deutlicher und erst nach ausdrücklicher Aktivierung erfolgen.

**R-029 – Prüfung der Ergebnisse · muss · umgesetzt**
KI-Ergebnisse gelten nicht automatisch als fachlich richtig. Eine optionale JSON-Zwischendatei muss die Prüfung und Bearbeitung vor dem Export ermöglichen.

## 5. Anki-Ausgabe und Deckverwaltung

**R-030 – APKG statt Zwischenimport · muss · umgesetzt**
Die primäre Ausgabe ist APKG, nicht CSV oder TSV. Neue Pakete werden mit `genanki` erzeugt. Der Standard-Notiztyp besitzt die Felder `Front` und `Back` sowie eine Vorlage für die Kartenrichtung Vorderseite zu Rückseite.

**R-031 – Neues Deck · muss · umgesetzt**
Beim Erzeugen eines neuen Decks ist der Deckname konfigurierbar. Ohne Angabe wird der Dateiname ohne Endung verwendet. Unterdecks mit `::` sind zulässig. Zielordner werden bei Bedarf angelegt.

**R-032 – Bestehende Ausgabe · muss · umgesetzt**
Ohne `--extend` darf eine vorhandene Ausgabedatei nicht überschrieben werden. Die Ausgabe muss auf `.apkg` enden. Diese Bedingungen müssen in der CLI-Hilfe verständlich beschrieben sein.

**R-033 – Deck erweitern · muss · umgesetzt**
Mit `--extend` muss eine bereits vorhandene APKG-Datei gelesen und um Karten in einem ausgewählten Deck erweitert werden können. Fehlt die Datei, ist dies ein Fehler. Existiert der gewünschte Deckname nicht im Paket, wird er angelegt. Das Programm verändert nur das angegebene APKG, niemals direkt die persönliche Anki-Sammlung.

**R-034 – Erhalt vorhandener Daten · muss · umgesetzt**
Beim Erweitern müssen vorhandene Notizen, Karten, Decks, Notiztypen, Lernstände und übrige Paket-Einträge erhalten bleiben. Schreibzugriffe auf die Sammlung erfolgen über die offizielle Anki-API. Das veränderte Paket muss über eine temporäre Datei und atomares Ersetzen geschrieben werden; ein Fehler darf nicht zu einem halb geschriebenen Ziel führen.

**R-035 – APKG-Formate · muss · umgesetzt**
Klassische Sammlungen (`collection.anki2`, `collection.anki21`) und aktuelle zstd-komprimierte Sammlungen (`collection.anki21b`) müssen lesbar und erweiterbar sein. Ein zstd-Paket muss nach der Erweiterung weiterhin zstd-komprimiert und mit der offiziellen Anki-API beziehungsweise SQLite lesbar sein.

**R-036 – Duplikate · muss · umgesetzt**
Doppelte Fragen müssen sowohl innerhalb der generierten Karten als auch beim Erweitern eines Zieldecks erkannt werden. Der Vergleich ignoriert Groß-/Kleinschreibung und unterschiedliche Whitespace-Anordnungen. Beim Erweitern gilt die Suche für das gesamte Zieldeck, auch wenn vorhandene Karten andere Notiztypen verwenden. Übersprungene Karten müssen in der Ergebnismeldung ausgewiesen werden.

**R-037 – Text und HTML · muss · umgesetzt**
KI-Kartentext ist Klartext und muss beim Schreiben nach Anki HTML-escaped werden. Zeichen wie `<`, `>` und `&` dürfen dadurch weder als aktives HTML ausgeführt noch bei der Duplikaterkennung falsch interpretiert werden.

**R-038 – Decks inspizieren · muss · umgesetzt**
Der Befehl `decks` muss alle normalen Decks eines APKG mit Namen, Kartenanzahl und ID auflisten. Gefilterte Decks werden nicht als normale Zieldecks angezeigt.

**R-039 – Datensicherung · soll · dokumentiert**
Vor dem Import eines erweiterten Pakets wird eine zusätzliche Anki-Sicherung empfohlen. Die atomare Dateiverarbeitung ersetzt keine fachliche Sicherung der persönlichen Sammlung.

## 6. JSON-Zwischendatei und reproduzierbarer Export

**R-040 – JSON speichern · muss · umgesetzt**
Mit `generate --json PFAD` müssen die generierten Karten zusätzlich als UTF-8-JSON gespeichert werden. Das Schema enthält `schema_version`, `deck`, `cards` und bei Generierung aus einem Dokument `source`. Das Speichern erfolgt atomar.

**R-041 – JSON validieren · muss · umgesetzt**
Beim Einlesen müssen Schema-Version, Objektstruktur und Karteninhalte validiert werden. Unbekannte Schema-Versionen, ungültiges JSON und ungültige Karten werden abgelehnt.

**R-042 – Export ohne KI · muss · umgesetzt**
Der Befehl `export` muss geprüfte JSON-Karten ohne erneuten KI-Aufruf in ein neues oder bestehendes APKG exportieren. Der Zieldeckname wird mit `--deck` angegeben; `--extend` entspricht dem Verhalten aus R-033 bis R-036.

## 7. Codequalität, Dokumentation und Unix-Prinzipien

Die folgenden Regeln gelten für bestehenden Code bei dessen Bearbeitung und verbindlich für jeden neuen oder geänderten Code. R-050 bis R-052 wurden für den gesamten Bestand umgesetzt und durch Ruff-Docstring- sowie Komplexitätsprüfungen abgesichert.

**R-050 – Never Nesting · muss · umgesetzt**
Kontrollfluss darf nicht unnötig verschachtelt werden. Verschachtelte Bedingungen und Schleifen müssen durch Guard Clauses, frühe Rückgaben, kleine fachliche Funktionen, Lookup-Tabellen oder klar benannte Strategien aufgelöst werden. Tiefe `if`/`for`/`try`-Pyramiden sind nicht zulässig. Das Auslagern von Komplexität in unklare Hilfsfunktionen gilt nicht als Verbesserung. Kontextmanager und syntaktisch notwendige Blöcke bleiben so flach und klein wie möglich.

**R-051 – Funktions- und Klassendokumentation · muss · umgesetzt**
Jede benannte Funktion, jede Methode und jede Klasse – einschließlich privater Hilfsfunktionen und Testfunktionen – muss einen aussagekräftigen Docstring besitzen. Dieser beschreibt mindestens:

1. Zweck und Verhalten,
2. alle Parameter mit Bedeutung und relevanten Einheiten/Grenzen,
3. den Rückgabewert beziehungsweise ausdrücklich `None`,
4. relevante Exceptions und nach außen sichtbare Seiteneffekte.

Bei Klassen werden zusätzlich wesentliche Attribute beziehungsweise Konstruktorparameter dokumentiert. „Keine Parameter“ oder „kein Rückgabewert“ muss nicht redundant ausgeschrieben werden; der Rückgabewert `None` ist jedoch anzugeben, wenn Seiteneffekte der Hauptzweck sind. Docstrings ergänzen Typannotationen, ersetzen sie aber nicht. Anonyme Ein-Zeilen-Lambdas sind nur für triviale Schlüssel/Adapter zulässig; fachliche Logik benötigt eine benannte, dokumentierte Funktion.

**R-052 – Kleine fachliche Einheiten · soll · umgesetzt**
Jede Funktion und jedes Modul soll eine klar benennbare Aufgabe erfüllen. Die Unix-Philosophie wird als Gestaltungsprinzip verstanden: kleine, kombinierbare Bausteine, eindeutige Schnittstellen und keine Vermischung von Dokumentzugriff, KI-Logik, Anki-Persistenz und Darstellung. Sie verlangt nicht künstlich viele Programme oder eine stdin/stdout-Schnittstelle für Binärdateien.

**R-053 – CLI-Hilfe · muss · offen**
`--help` muss für das Hauptprogramm und jeden Unterbefehl vollständig erklären:

- Zweck und typischer Ablauf,
- kurze und lange Optionsnamen,
- Pflicht- und optionalen Parameter,
- Standardwerte und Wertebereiche,
- Dateiformate und Pfadinterpretation,
- Verhalten bei vorhandener beziehungsweise fehlender Ausgabedatei,
- Zusammenhang von `--extend`, Deckname und Ausgabe,
- Bedeutung von `--limit 0`,
- mindestens ein praxisnahes Beispiel.

Die Hilfe muss aus den tatsächlichen Optionen erzeugt werden und darf nicht vom Programmverhalten abweichen.

**R-054 – CLI-Verhalten und Exit-Codes · muss · teilweise umgesetzt**
Erfolgreiche Befehle enden mit Exit-Code 0. Erwartete Anwendungs-, Eingabe-, Konfigurations- und Providerfehler enden ungleich 0 und werden ohne unnötigen Traceback auf `stderr` ausgegeben. Hilfe und normale Ergebnisse erscheinen auf `stdout`. Programmeingaben werden über Optionen und Argumente gesteuert; eine interaktive Sitzung ist für den Normalablauf nicht erforderlich.

**R-055 – Dokumentationssynchronität · muss · dauerhaft**
README, CLI-Hilfe, Anforderungen, Beispielkonfiguration und tatsächliches Verhalten müssen übereinstimmen. Bei jeder Verhaltensänderung sind direkt betroffene Dokumente im selben Anforderungspaket zu aktualisieren. Neue Funktionen dürfen nicht als fertig dokumentiert werden, bevor sie implementiert und validiert sind.

## 8. Tests und schrittweise Entwicklung

**R-060 – Verhaltensbezogene Tests · muss · umgesetzt und fortlaufend offen**
Jede neue oder geänderte Verhalten muss durch fokussierte Tests abgesichert werden. Zu prüfen sind der erfolgreiche Ablauf, relevante Grenzwerte, ungültige Eingaben und nachweisbare Regressionen. Bestehende Tests müssen erweitert oder angepasst werden, wenn sich beabsichtigt das Verhalten ändert; reine Implementierungs- oder Konstantenwiederholungen zählen nicht als sinnvoller Test.

**R-061 – Testabdeckung der Kernrisiken · muss · umgesetzt**
Die Tests müssen mindestens Dokumentextraktion, Textaufteilung, Kartenlimit, Unlimited-Prompt, KI-Validierung, JSON-Roundtrip, Duplikate, APKG-Neuerstellung und -Erweiterung, Erhalt des Lernstands, HTML-Escaping, Medien-Einträge, aktuelle zstd-Pakete und zentrale CLI-Abläufe abdecken. Ein tatsächlich mit der offiziellen Anki-API exportiertes aktuelles Paket muss im Integrationstest erweitert werden.

**R-062 – Externe Dienste in Tests · muss · umgesetzt und dauerhaft**
Der reguläre Testlauf benötigt weder API-Schlüssel noch externe Netzwerkdienste. KI-Antworten werden simuliert; ein optionaler End-to-End-Test kann einen lokalen OpenAI-kompatiblen Testserver verwenden. Reale Provider-Tests sind ausdrücklich optional, kosten- und datenschutzbewusst und niemals Voraussetzung für den Standardtestlauf.

**R-063 – Validierung · muss · dauerhaft**
Vor dem Abschluss eines Codepakets sind zunächst gezielte Tests und anschließend die relevanten Gesamtprüfungen auszuführen. Standard sind Ruff-Lint, Ruff-Formatprüfung und pytest. Reine Dokumentationsänderungen benötigen keine Code-Tests, sofern keine Dokumentationstests vorhanden sind.

**R-064 – Kleine Commits · muss · dauerhaft**
Die Arbeit erfolgt Anforderung für Anforderung in kleinen, nachvollziehbaren Schritten. Jedes abgeschlossene und validierte, zusammengehörige Anforderungspaket erhält einen eigenen Commit. Viele unabhängige Requirements dürfen nicht erst am Ende in einem großen Commit gesammelt werden. Unzusammenhängende Änderungen und unbekannte Nutzeränderungen gehören nicht in denselben Commit.

## 9. Zentrale Konfiguration

Diese Anforderungen sind neu und noch nicht implementiert. `.env` bleibt für Geheimnisse und die bestehende einfache Nutzung relevant; die neue Konfiguration ersetzt keine sichere Speicherung von Schlüsseln.

**R-110 – Konfigurationsdatei · muss · offen**
Das Programm muss eine zentrale, strukturierte **YAML**-Konfiguration unterstützen. Standarddatei ist `config.yaml` im aktuellen Arbeitsverzeichnis; ein abweichender Pfad wird über `--config` oder `ANKI_CONFIG` gewählt. Eine fehlende implizite Standarddatei bedeutet eingebaute Defaults. Eine ausdrücklich angegebene, fehlende oder ungültige Datei ist ein Fehler.

**R-111 – Version und Validierung · muss · offen**
Die Datei besitzt eine `schema_version` und wird beim Start mit einem typisierten Schema validiert. Unbekannte Versionen, ungültige Typen und unbekannte Felder müssen mit Angabe des betroffenen Konfigurationsschlüssels abgelehnt werden. Eine kommentierte `config.example.yaml` wird versioniert; die persönliche `config.yaml` wird ignoriert, damit keine lokalen Pfade oder versehentlichen Geheimnisse committet werden.

**R-112 – Modellprofile und Bausteine · muss · offen**
Die Konfiguration muss benannte, wiederverwendbare Modellprofile unterstützen. Ein Profil enthält mindestens:

- eindeutigen Profilnamen,
- LiteLLM-Modellkennung `provider/modell`,
- optionalen API-Endpunkt,
- Namen der Umgebungsvariablen für den API-Schlüssel, nicht den Schlüssel selbst,
- Timeout,
- PDF-Verarbeitungsmodus aus R-120,
- optional provider-spezifische, erlaubte Zusatzparameter.

Vorgefertigte, auskommentierte oder aktivierbare Bausteine müssen OpenAI, Anthropic, Gemini, Moonshot und Ollama abdecken. Ein Standardprofil ist wählbar. Direkte `--model`-Angaben bleiben ohne Profil möglich.

**R-113 – Eingabe- und Ausgabeordner · muss · offen**
In der Konfiguration müssen Standardordner für Eingabe und Ausgabe festlegbar sein. Reine Dateinamen werden unter diesen Ordnern aufgelöst. Ausdrücklich angegebene relative CLI-Pfade bleiben relativ zum aktuellen Arbeitsverzeichnis; relative Pfade innerhalb der YAML-Datei werden relativ zum Speicherort der YAML-Datei aufgelöst. Absolute Pfade bleiben unverändert. Wenn nur ein Ausgabeordner vorgegeben ist, lautet der Standarddateiname `<eingabedateiname>.apkg`.

**R-114 – Generierungsdefaults · muss · offen**
Die Konfiguration muss die wesentlichen CLI-Parameter als Defaults speichern können: Modellprofil, Kartenlimit, Sprache, zusätzliche Anweisungen, Abschnittsgröße, Timeout, Deckname beziehungsweise Namensregel, JSON-Ausgabe, Extend-Modus und PDF-Verarbeitungsmodus. Nicht jede Konfiguration muss jeden Schlüssel setzen; fehlende Werte verwenden die eingebauten Defaults.

**R-115 – Eindeutige Priorität · muss · offen**
Für jeden effektiven Wert gilt von niedriger zu hoher Priorität:

1. eingebauter Programmdefault,
2. Wert aus der ausgewählten YAML-Konfiguration beziehungsweise dem gewählten Profil,
3. unterstützte Umgebungsvariable beziehungsweise `.env`,
4. ausdrücklich gesetzter CLI-Wert.

CLI-Werte müssen Konfigurationsdefaults daher immer überschreiben. Secrets werden ausschließlich aus der Umgebung gelesen. Für konfigurierbare boolesche Werte müssen CLI-Optionen beide Richtungen ermöglichen, beispielsweise `--extend/--no-extend`, damit auch ein konfigurierter `true`-Wert überschrieben werden kann.

**R-116 – Konfiguration anzeigen · soll · offen**
Ein Diagnosebefehl soll die effektiv zusammengeführte Konfiguration und deren Herkunft anzeigen können. Geheimnisse müssen dabei vollständig weggelassen oder eindeutig maskiert werden. Dies erleichtert Support und spätere Web-UI-Validierung.

**R-117 – Web-Kompatibilität · muss · offen**
Laden, Validieren und Zusammenführen der Konfiguration muss als UI-unabhängiger Dienst implementiert werden. Eine spätere Webanwendung muss dieselben Schemas und Regeln verwenden und Änderungen validiert sowie atomar speichern können. CLI-spezifische Objekte gehören nicht in das Konfigurationsschema.

**R-118 – Bestehende Nutzung · muss · offen**
Bestehende Aufrufe ohne YAML-Datei müssen weiterhin funktionieren. Die Einführung der Konfiguration darf weder API-Schlüssel erzwingen noch bestehende `--model`- und `.env`-Workflows grundlos brechen.

**R-119 – Konfigurationstests · muss · offen**
Tests müssen mindestens leere Datei, fehlende implizite und explizite Datei, ungültige YAML/Typen/Felder, Profilauflösung, Pfadauflösung, sämtliche Prioritätsebenen, boolesche CLI-Überschreibung, Secret-Nichtpersistenz und atomares Speichern abdecken.

## 10. Native PDF-Verarbeitung durch KI-Provider

**R-120 – Wählbarer PDF-Modus · muss · offen**
Pro Modellprofil muss `pdf_mode` mindestens die Werte `local` und `native` unterstützen. `local` ist der Standard und verwendet die vorhandene Textextraktion. `native` überspringt diese Extraktion und übergibt die Original-PDF über eine provider-eigene Datei-/Dokumentschnittstelle. Ein entsprechender CLI-Wert überschreibt den Profilwert.

**R-121 – Fähigkeiten nicht raten · muss · offen**
Native Verarbeitung darf nur für tatsächlich unterstützte Provider-/Modellkombinationen freigeschaltet werden. Vor Implementierung eines Adapters müssen die aktuellen offiziellen Provider- und LiteLLM-Dokumente geprüft werden. Die technische Fähigkeitenmatrix muss Provider, Modell einschließlich Einschränkungen, Dateigröße/Seitenlimit, unterstützte Antwortstruktur, Dokumentationslink und Prüfdatum enthalten. Es ist nicht erforderlich, jeden Provider zu unterstützen; eine klare Fehlermeldung ist besser als ein ungeprüfter Upload.

**R-122 – Adapter und gleiches Ergebnis · muss · offen**
Native Dokumentverarbeitung wird über einen provider-spezifischen Adapter hinter der gemeinsamen Generierungsschnittstelle implementiert. Upload, Verweis auf die hochgeladene Datei und Antwortabruf folgen der offiziellen API des jeweiligen Anbieters. Die Antwort muss trotzdem demselben Karten-JSON-Schema entsprechen und dieselbe Validierung, Deduplizierung und APKG-Ausgabe durchlaufen. Andere Dateiformate bleiben auf lokaler Extraktion, bis ein eigener geprüfter Adapter vorhanden ist.

**R-123 – Datenschutz, Kosten und Fallback · muss · offen**
`native` bedeutet bei Cloud-Providern die Übertragung der vollständigen Originaldatei und muss in Hilfe, Profil und Dokumentation ausdrücklich gekennzeichnet sein. Dateigröße und bekannte Providergrenzen werden vor dem Upload geprüft. Bei fehlender Unterstützung oder einem Uploadfehler darf nicht stillschweigend lokal extrahiert oder ein anderes Modell gewählt werden; ein Fallback erfordert eine eigene ausdrückliche Option. Informationen zu Speicherung beziehungsweise Löschung hochgeladener Dateien müssen entsprechend der Provider-API berücksichtigt und dokumentiert werden.

**R-124 – Native-Verarbeitung testen · muss · offen**
Unit-Tests müssen Auswahl und Vorrang des PDF-Modus, fehlende Provider-Fähigkeit, lokale Extraktion ohne Upload, native Übergabe ohne lokale Extraktion, Upload-/Antwortfehler und ungültige native Antworten prüfen. Ein regulärer Testlauf darf keine Originaldatei an einen externen Dienst übertragen.

## 11. Spätere Erweiterungen

Die folgenden Punkte sind Ideen und keine aktuellen Implementierungsaufträge:

- **R-200 · kann · später:** Webinterface beziehungsweise Web-API auf dem vorhandenen fachlichen Kern; Konfiguration und Kartenprüfung über dieselben Dienste.
- **R-201 · kann · später:** Linux-Container und Deployment auf Proxmox, erst nach stabiler Anwendung und geklärter Verwaltung von Konfiguration, Secrets und Daten.
- **R-202 · kann · später:** URLs als zusätzliche Quelle mit eigenen Sicherheits- und Datenschutzregeln.
- **R-203 · kann · später:** OCR für gescannte Dokumente.
- **R-204 · kann · später:** Quellenangaben pro Karte, interaktive Prüfung und Fortsetzen abgebrochener Generierungen.
- **R-205 · kann · später:** Lückentext, weitere Notiztypen sowie Bilder und Audio in Karten.

## 12. Aktuelle CLI-Vertragsgrundlage

Bis zur Umsetzung der neuen Konfigurations- und Hilfeanforderungen bestehen diese Befehle:

- `generate EINGABE --output ZIEL.apkg [--deck NAME] [--model PROVIDER/MODELL] [--limit N] [--extend] [--json DATEI]`
- `export KARTEN.json --output ZIEL.apkg --deck NAME [--extend]`
- `decks PAKET.apkg`

Wichtige Ist-Eigenschaften:

- `--output` ist derzeit bei `generate` und `export` erforderlich; Ausgabeordner aus YAML sind offen.
- `--deck` ist bei `generate` optional und bei `export` erforderlich.
- Ohne `--extend` muss die Ausgabedatei neu sein; mit `--extend` muss sie bereits existieren.
- Fehlende Elternordner der Ausgabe werden erstellt.
- `--limit` akzeptiert nichtnegative ganze Zahlen; `0` bedeutet Unlimited.
- API-Schlüssel werden über provider-spezifische Umgebungsvariablen oder `LLM_API_KEY` bereitgestellt.

## 13. Abnahmekriterien für die noch offenen Hauptpakete

### A. Qualitäts- und CLI-Paket (req-2)

1. Neue und geänderte Funktionen/Klassen besitzen vollständige Docstrings; für den Bestand existiert ein nachvollziehbarer, vollständig abgearbeiteter Refactoring-Stand.
2. Der fachliche Code enthält keine unnötig verschachtelten Kontrollflüsse; Refactorings ändern nachweisbar kein Verhalten.
3. Haupt- und Unterbefehlshilfe erklären Optionen, Defaults, Pflichtwerte, Dateibehandlung und Beispiele vollständig.
4. Tests prüfen Hilfe und Fehlerausgaben; Ruff und pytest sind erfolgreich.
5. README und diese Datei spiegeln den tatsächlichen Stand wider.
6. Die Umsetzung ist in nachvollziehbaren Einzel-Commits dokumentiert.

### B. Konfigurationspaket (req-3, Konfiguration)

1. Eine Beispiel-YAML enthält sichere Bausteine für die genannten Provider und alle dokumentierten Defaults.
2. Ohne YAML bleibt der bisherige Workflow funktionsfähig.
3. Effektive Werte folgen nachweislich R-115; CLI überschreibt auch konfigurierte boolesche Werte.
4. Eingabe-/Ausgabeordner und relative Pfade verhalten sich eindeutig.
5. Keine Secret-Werte erscheinen in YAML, Diagnoseausgaben, Logs oder Git.
6. Validierung, atomare Speicherung und Web-unabhängiger Konfigurationsdienst sind getestet und dokumentiert.

### C. Native-PDF-Paket (req-3, Provider)

1. Mindestens ein offiziell belegter Provider-/Modelladapter unterstützt native PDF-Verarbeitung; weitere Adapter folgen nur nach Dokumentationsprüfung.
2. `local` bleibt Standard; `native` wird nur ausdrücklich aktiviert.
3. Native Verarbeitung umgeht nachweisbar die lokale Extraktion und erzeugt trotzdem validierte Standardkarten.
4. Nicht unterstützte Modelle, Dateigrenzen und Fehler werden verständlich gemeldet; kein stiller Datentransfer oder Fallback findet statt.
5. Datenschutz, Upload-Lebenszyklus, Grenzen und getestete Provider sind dokumentiert.
6. Alle Tests laufen ohne echten externen Datei-Upload.
