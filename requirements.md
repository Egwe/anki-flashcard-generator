# Anforderungen – Anki Flashcard Generator

## 1. Zweck und Geltung

Dieses Dokument bündelt alle fachlichen und technischen Anforderungen aus [req.md](./req.md), [req-2.md](./req-2.md), [req-3.md](./req-3.md), [req-4.md](./req-4.md) und [req-5.md](./req-5.md). Es ergänzt die Entscheidungen und Funktionen, die bereits beim ersten MVP entstanden sind. Die fünf Ausgangsdateien bleiben als Originalvorgaben erhalten; dieses Dokument ist die konsolidierte Arbeitsgrundlage.

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
Langer extrahierter Text muss für Modellaufrufe in überlappende Abschnitte aufgeteilt werden. Standard sind 24.000 Zeichen pro Abschnitt und 500 Zeichen Überlappung, höchstens jedoch ein Viertel der Abschnittsgröße (bei 1.000 Zeichen also 250). Die CLI erlaubt Abschnittsgrößen von 1.000 bis 100.000 Zeichen; jede Größe aus diesem Bereich muss ohne Fehler verarbeitet werden. Absätze und Wortgrenzen sollen bevorzugt werden; jeder Quelltext muss trotz Überschneidungen vollständig berücksichtigt werden.

**R-013 – OCR · muss · offen über R-142**
Gescannte PDFs ohne Textebene benötigen derzeit eine externe OCR. Mit req-5 wird eine eingebaute OCR im strukturierten PDF-Modus verlangt (R-142); der Modus `local` bleibt bei der eingebetteten Textebene.

**R-014 – Native Dokumentverarbeitung · muss · umgesetzt für geprüfte OpenAI-Modelle**
Die lokale Extraktion muss für geeignete Modelle optional durch die native Verarbeitung der Originaldatei beim Provider ersetzt werden können.

## 4. KI-Modelle und Karteikartengenerierung

**R-020 – Provider-Unabhängigkeit · muss · umgesetzt**
Gängige KI-Anbieter müssen über eine gemeinsame Schnittstelle ansprechbar sein. LiteLLM bildet diese Schnittstelle; Modelle werden in der Form `provider/modell` angegeben. Vorgesehen und dokumentiert sind insbesondere OpenAI, Anthropic, Google Gemini, Moonshot/Kimi und Ollama. Weitere von LiteLLM unterstützte Provider sollen ohne eigene CLI-Befehle nutzbar sein.

**R-021 – Provider-Parameter · muss · umgesetzt**
Modell, API-Endpunkt und Timeout werden primär über YAML-Modellprofile konfiguriert und können durch explizite CLI-Optionen überschrieben werden. API-Schlüssel werden ausschließlich über `.env` beziehungsweise Umgebungsvariablen bereitgestellt. `ANKI_MODEL` und `LLM_API_BASE` sind keine Konfigurationsschicht und werden nicht ausgewertet.

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

**R-028 – Datenschutz · muss · umgesetzt**
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

**R-053 – CLI-Hilfe · muss · umgesetzt**
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

**R-054 – CLI-Verhalten und Exit-Codes · muss · umgesetzt**
Erfolgreiche Befehle enden mit Exit-Code 0. Erwartete Anwendungs-, Eingabe-, Konfigurations- und Providerfehler enden ungleich 0 und werden ohne unnötigen Traceback auf `stderr` ausgegeben. Hilfe und normale Ergebnisse erscheinen auf `stdout`. Programmeingaben werden über Optionen und Argumente gesteuert; eine interaktive Sitzung ist für den Normalablauf nicht erforderlich.

**R-055 – Dokumentationssynchronität · muss · dauerhaft**
README, CLI-Hilfe, Anforderungen, Beispielkonfiguration und tatsächliches Verhalten müssen übereinstimmen. Bei jeder Verhaltensänderung sind direkt betroffene Dokumente im selben Anforderungspaket zu aktualisieren. Neue Funktionen dürfen nicht als fertig dokumentiert werden, bevor sie implementiert und validiert sind.

## 8. Tests und schrittweise Entwicklung

**R-060 – Verhaltensbezogene Tests · muss · umgesetzt und dauerhaft fortzuführen**
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

Der Konfigurationsservice ist vollständig in die CLI integriert: versioniertes YAML, Profile, Prioritäten, Pfadregeln, atomare Speicherung und geschwärzte Diagnose sind implementiert und getestet. `.env` bleibt für Geheimnisse und die bestehende einfache Nutzung relevant; die Konfiguration ersetzt keine sichere Speicherung von Schlüsseln.

**R-110 – Konfigurationsdatei · muss · umgesetzt**
Das Programm muss eine zentrale, strukturierte **YAML**-Konfiguration unterstützen. Standarddatei ist `config.yaml` im aktuellen Arbeitsverzeichnis; ein abweichender Pfad wird über `--config` oder `ANKI_CONFIG` gewählt. Eine fehlende implizite Standarddatei bedeutet eingebaute Defaults. Eine ausdrücklich angegebene, fehlende oder ungültige Datei ist ein Fehler.

**R-111 – Version und Validierung · muss · umgesetzt**
Die Datei besitzt eine `schema_version` und wird beim Start mit einem typisierten Schema validiert. Unbekannte Versionen, ungültige Typen und unbekannte Felder müssen mit Angabe des betroffenen Konfigurationsschlüssels abgelehnt werden. Eine kommentierte `config.example.yaml` wird versioniert; die persönliche `config.yaml` wird ignoriert, damit keine lokalen Pfade oder versehentlichen Geheimnisse committet werden.

**R-112 – Modellprofile und Bausteine · muss · umgesetzt**
Die Konfiguration muss benannte, wiederverwendbare Modellprofile unterstützen. Ein Profil enthält mindestens:

- eindeutigen Profilnamen,
- LiteLLM-Modellkennung `provider/modell`,
- optionalen API-Endpunkt,
- Namen der Umgebungsvariablen für den API-Schlüssel, nicht den Schlüssel selbst,
- Timeout,
- PDF-Verarbeitungsmodus aus R-120,
- optional provider-spezifische, erlaubte Zusatzparameter.

Vorgefertigte, auskommentierte oder aktivierbare Bausteine müssen OpenAI, Anthropic, Gemini, Moonshot und Ollama abdecken. Ein Standardprofil ist wählbar. Direkte `--model`-Angaben bleiben ohne Profil möglich.

**R-113 – Eingabe- und Ausgabeordner · muss · umgesetzt**
In der Konfiguration müssen Standardordner für Eingabe und Ausgabe festlegbar sein. Reine Dateinamen werden unter diesen Ordnern aufgelöst. Ausdrücklich angegebene relative CLI-Pfade bleiben relativ zum aktuellen Arbeitsverzeichnis; relative Pfade innerhalb der YAML-Datei werden relativ zum Speicherort der YAML-Datei aufgelöst. Absolute Pfade bleiben unverändert. Wenn nur ein Ausgabeordner vorgegeben ist, lautet der Standarddateiname `<eingabedateiname>.apkg`.

**R-114 – Generierungsdefaults · muss · umgesetzt**
Die Konfiguration muss die wesentlichen CLI-Parameter als Defaults speichern können: Modellprofil, Kartenlimit, Sprache, zusätzliche Anweisungen, Abschnittsgröße, Timeout, Deckname beziehungsweise Namensregel, JSON-Ausgabe, Extend-Modus und PDF-Verarbeitungsmodus. Nicht jede Konfiguration muss jeden Schlüssel setzen; fehlende Werte verwenden die eingebauten Defaults.

**R-115 – Eindeutige Priorität · muss · umgesetzt**
Für jeden effektiven Wert gilt von niedriger zu hoher Priorität:

1. eingebauter Programmdefault,
2. Wert aus der ausgewählten YAML-Konfiguration beziehungsweise dem gewählten Profil,
3. ausdrücklich gesetzter CLI-Wert.

`.env` beziehungsweise Umgebungsvariablen bilden **keine** Konfigurationsschicht für Modelle, Endpunkte oder Generierungsparameter. Sie liefern ausschließlich Zugangsdaten für das in YAML referenzierte `api_key_env`. `ANKI_CONFIG` wählt nur den YAML-Dateipfad aus. Frühere Variablen `ANKI_MODEL` und `LLM_API_BASE` werden ignoriert. CLI-Werte müssen Konfigurationsdefaults daher immer überschreiben. Secrets werden ausschließlich aus der Umgebung gelesen. Für konfigurierbare boolesche Werte müssen CLI-Optionen beide Richtungen ermöglichen, beispielsweise `--extend/--no-extend`, damit auch ein konfigurierter `true`-Wert überschrieben werden kann.

**R-116 – Konfiguration anzeigen · soll · umgesetzt**
Ein Diagnosebefehl soll die effektiv zusammengeführte Konfiguration und deren Herkunft anzeigen können. Geheimnisse müssen dabei vollständig weggelassen oder eindeutig maskiert werden. Dies erleichtert Support und spätere Web-UI-Validierung.

**R-117 – Web-Kompatibilität · muss · umgesetzt**
Laden, Validieren und Zusammenführen der Konfiguration muss als UI-unabhängiger Dienst implementiert werden. Eine spätere Webanwendung muss dieselben Schemas und Regeln verwenden und Änderungen validiert sowie atomar speichern können. CLI-spezifische Objekte gehören nicht in das Konfigurationsschema.

**R-118 – Bestehende Nutzung · muss · umgesetzt**
Bestehende Aufrufe ohne YAML-Datei müssen weiterhin funktionieren. Die Einführung der Konfiguration darf weder API-Schlüssel erzwingen noch bestehende `--model`- und `.env`-Workflows grundlos brechen.

**R-119 – Konfigurationstests · muss · umgesetzt**
Tests müssen mindestens leere Datei, fehlende implizite und explizite Datei, ungültige YAML/Typen/Felder, Profilauflösung, Pfadauflösung, sämtliche Prioritätsebenen, boolesche CLI-Überschreibung, Secret-Nichtpersistenz und atomares Speichern abdecken. Sie müssen zusätzlich beweisen, dass `ANKI_MODEL` und `LLM_API_BASE` YAML nicht überschreiben und dass Credential-Variablen aus `.env` weiterhin funktionieren.

## 10. Native PDF-Verarbeitung durch KI-Provider

**R-120 – Wählbarer PDF-Modus · muss · umgesetzt**
Pro Modellprofil muss `pdf_mode` mindestens die Werte `local` und `native` unterstützen. `local` ist der Standard und verwendet die vorhandene Textextraktion. `native` überspringt diese Extraktion und übergibt die Original-PDF über eine provider-eigene Datei-/Dokumentschnittstelle. Ein entsprechender CLI-Wert überschreibt den Profilwert.

**R-121 – Fähigkeiten nicht raten · muss · umgesetzt**
Native Verarbeitung darf nur für tatsächlich unterstützte Provider-/Modellkombinationen freigeschaltet werden. Vor Implementierung eines Adapters müssen die aktuellen offiziellen Provider- und LiteLLM-Dokumente geprüft werden. Die technische Fähigkeitenmatrix muss Provider, Modell einschließlich Einschränkungen, Dateigröße/Seitenlimit, unterstützte Antwortstruktur, Dokumentationslink und Prüfdatum enthalten. Es ist nicht erforderlich, jeden Provider zu unterstützen; eine klare Fehlermeldung ist besser als ein ungeprüfter Upload.

**R-122 – Adapter und gleiches Ergebnis · muss · umgesetzt**
Native Dokumentverarbeitung wird über einen provider-spezifischen Adapter hinter der gemeinsamen Generierungsschnittstelle implementiert. Upload, Verweis auf die hochgeladene Datei und Antwortabruf folgen der offiziellen API des jeweiligen Anbieters. Die Antwort muss trotzdem demselben Karten-JSON-Schema entsprechen und dieselbe Validierung, Deduplizierung und APKG-Ausgabe durchlaufen. Andere Dateiformate bleiben auf lokaler Extraktion, bis ein eigener geprüfter Adapter vorhanden ist.

**R-123 – Datenschutz, Kosten und Fallback · muss · umgesetzt**
`native` bedeutet bei Cloud-Providern die Übertragung der vollständigen Originaldatei und muss in Hilfe, Profil und Dokumentation ausdrücklich gekennzeichnet sein. Dateigröße und bekannte Providergrenzen werden vor dem Upload geprüft. Bei fehlender Unterstützung oder einem Uploadfehler darf nicht stillschweigend lokal extrahiert oder ein anderes Modell gewählt werden; ein Fallback erfordert eine eigene ausdrückliche Option. Informationen zu Speicherung beziehungsweise Löschung hochgeladener Dateien müssen entsprechend der Provider-API berücksichtigt und dokumentiert werden.

**R-124 – Native-Verarbeitung testen · muss · umgesetzt**
Unit-Tests müssen Auswahl und Vorrang des PDF-Modus, fehlende Provider-Fähigkeit, lokale Extraktion ohne Upload, native Übergabe ohne lokale Extraktion, Upload-/Antwortfehler und ungültige native Antworten prüfen. Ein regulärer Testlauf darf keine Originaldatei an einen externen Dienst übertragen.

## 11. KI-gestützte Unterdecks (req-4)

Ziel aus [req-4.md](./req-4.md): Ein Deck steht beispielsweise für eine Vorlesung, seine Unterdecks für deren Kapitel. Das KI-Modell soll neue Karten nicht nur anhängen, sondern inhaltlich passenden Unterdecks zuordnen. Mehrere Dokumente derselben Vorlesung werden nacheinander verarbeitet; dabei dient das vorhandene Deck als Kontext, damit passende Unterdecks wiederverwendet und nur bei Bedarf neue angelegt werden. Die Umsetzung kombiniert zusätzliche Modellanweisungen mit einem erweiterten, streng validierten Antwortformat.

**R-130 – Unterdeck-Modus · muss · umgesetzt**
Ein ausdrücklich aktivierbarer Modus (`--subdecks/--no-subdecks`, YAML `generation.subdecks`, Standard: aus) lässt das Modell jede Karte genau einem Unterdeck zuordnen. Das mit `--deck` beziehungsweise der bestehenden Namensregel bestimmte Deck ist dann das übergeordnete Deck; Karten landen in `Deck::Unterdeck`. Ohne den Modus bleibt das bisherige Verhalten unverändert. Der CLI-Wert überschreibt YAML in beiden Richtungen.

**R-131 – Unterdecks aus der Quelle · muss · umgesetzt**
Das Modell bildet Unterdecknamen inhaltlich und orientiert sich dabei vorrangig an der Struktur der Quelle, etwa Kapitel- und Abschnittsüberschriften, Nummerierungen oder einem Inhaltsverzeichnis. Innerhalb einer Generierung über mehrere Textabschnitte werden bereits vergebene Unterdecknamen an spätere Anfragen weitergegeben, damit gleiche Kapitel gleich heißen.

**R-132 – Vorhandenes Deck als Kontext · muss · umgesetzt**
Beim Erweitern (`--extend`) werden die vorhandenen direkten Unterdecks des Zieldecks aus dem APKG gelesen und mit einer begrenzten Zahl von Beispielfragen an das Modell übergeben. Das Modell muss passende vorhandene Unterdecks bevorzugen und darf nur für nicht passende Inhalte neue anlegen. Das Lesen des Kontexts verändert das Paket nicht. Dadurch lassen sich mehrere Dokumente einer Vorlesung nacheinander konsistent einordnen.

**R-133 – Antwortformat und Validierung · muss · umgesetzt**
Im Unterdeck-Modus verlangt das Antwortschema je Karte das Pflichtfeld `subdeck`. Unterdecknamen werden mit Pydantic validiert: nicht leer, höchstens 100 Zeichen, eine Ebene ohne `::`. Ungültige Antworten sind wie bisher ein verständlicher Fehler. Namen, die sich von vorhandenen oder bereits vergebenen Unterdecks nur in Groß-/Kleinschreibung oder Leerraum unterscheiden, werden auf deren Schreibweise vereinheitlicht. Ohne aktivierten Modus werden etwaige `subdeck`-Angaben des Modells verworfen.

**R-134 – Anki-Ausgabe mit Unterdecks · muss · umgesetzt**
Neue Pakete enthalten das übergeordnete Deck und alle verwendeten Unterdecks. Beim Erweitern werden fehlende Unterdecks über die offizielle Anki-API angelegt; vorhandene Karten, Lernstände und Unterdecks bleiben erhalten. Die Duplikatprüfung umfasst bei Karten mit Unterdeck das übergeordnete Deck einschließlich aller Unterdecks. Die Ergebnismeldung weist die hinzugefügten Karten je Unterdeck aus.

**R-135 – JSON und Export · muss · umgesetzt**
Karten-JSON enthält das optionale Feld `subdeck`; Schema-Version 1 bleibt rückwärtskompatibel, Karten ohne Unterdeck werden unverändert geschrieben. `export` legt Karten mit `subdeck` ohne KI-Aufruf unter `--deck::subdeck` ab.

**R-136 – Native PDF-Verarbeitung · soll · umgesetzt**
Der Unterdeck-Modus funktioniert auch mit dem geprüften nativen OpenAI-Adapter und verwendet dieselben Anweisungen, dasselbe Antwortschema und dieselbe Validierung.

**R-137 – Tests · muss · umgesetzt**
Tests decken Prompt-Anweisungen und Kontext, Weitergabe neuer Unterdecks zwischen Abschnitten, Namensvereinheitlichung, Verwerfen von Unterdecks ohne Modus, Validierung, APKG-Erzeugung und -Erweiterung mit Unterdecks, Duplikate über Unterdecks hinweg, unveränderliches Lesen des Kontexts, JSON-Roundtrip, Export, Konfigurationspriorität, CLI-Integration und den nativen Weg ab – ohne echte KI-Aufrufe.

**R-138 – Dokumentation · muss · umgesetzt**
README, Benutzerhandbuch, Entwicklerhandbuch, CLI-Hilfe und `config.example.yaml` beschreiben Modus, Ablauf für mehrere Dokumente, Kontextübertragung an den Provider, Grenzen und Beispiele.

## 12. Vollständige lokale PDF-Aufbereitung (req-5)

Ziel aus [req-5.md](./req-5.md): Auch PDFs mit vielen Abbildungen, Diagrammen und Tabellen – typisch für Vorlesungsfolien und Skripte – sollen ohne Informationsverlust in Karten einfließen. Dazu wird die PDF lokal so vollständig wie möglich in Text umgewandelt; an das Kartenmodell geht danach nur noch Text. Für die Umwandlung werden vorhandene Open-Source-Werkzeuge genutzt, die selbst lokale KI-Modelle für Layout, Tabellen, Texterkennung und Bilder einsetzen. Das Problem wird nicht von Grund auf neu gelöst.

**Kernproblem.** Der Modus `local` liest mit pypdf nur die eingebettete Textebene. Dabei geht verloren:

- Text, der nur als Bild vorliegt: gescannte Seiten, Screenshots, als Bild eingefügte Folieninhalte;
- Information, die nur grafisch dargestellt ist: Diagramme, Schaltpläne, Abbildungen samt Achsen und Beschriftungen;
- die Struktur von Tabellen: Zellen werden zu Fließtext ohne Zeilen- und Spaltenbezug;
- Formeln, deren Symbole, Hoch- und Tiefstellungen in der Textebene oft verstümmelt sind;
- die Lesereihenfolge bei mehrspaltigem Layout sowie die Trennung von Kopf- und Fußzeilen.

Seiten ohne Textebene werden heute stillschweigend übersprungen; nur ein vollständig textloses Dokument führt zu einem Fehler. Der Modus `native` (Abschnitt 10) gibt dem Modell zusätzlich Seitenbilder, funktioniert aber nur für geprüfte OpenAI-Modelle, überträgt die Originaldatei und steht lokalen Textmodellen nicht zur Verfügung.

**Machbarkeit.** Text, Lesereihenfolge, Tabellen und Texterkennung sind mit etablierten Bibliotheken zuverlässig und auf einer normalen CPU lösbar. Formeln sind lösbar, verlangsamen die Aufbereitung aber deutlich. Abbildungen lassen sich nur annähernd in Text übersetzen: Die Beschreibung stammt von einem Bild-Sprach-Modell (VLM), ihre Qualität hängt stark von dessen Größe ab, und sie kann Fehler enthalten. Kleine Modelle laufen auf der CPU, liefern aber eher kurze Bildunterschriften; für technische Diagramme sind größere Modelle über einen lokalen Endpunkt wie Ollama oder auf einer GPU realistisch. „Vollständig“ bedeutet daher: Jede Seite und jedes Element ist im Text vertreten oder als nicht lesbar gemeldet – nicht, dass jede grafische Information verlustfrei übertragen wird. Der Preis sind schwere optionale Abhängigkeiten (PyTorch, Modelldateien von einigen hundert MB bis zu mehreren GB) und Laufzeiten im Bereich von Sekunden pro Seite statt Millisekunden, mit Bildbeschreibung auf der CPU auch deutlich mehr.

**Voruntersuchung** (Stand 20.11.2026, Quellen: offizielle Projektseiten, READMEs und PyPI; endgültige Auswahl nach R-141):

| Kandidat | Lizenz | Stärken | Einschränkungen |
|---|---|---|---|
| Docling 2.151.1 | MIT | Layoutanalyse, Tabellenstruktur (TableFormer), OCR (u. a. RapidOCR, EasyOCR, Tesseract), Formeln als LaTeX, Bildbeschreibung mit lokalen VLMs (SmolVLM-256M, Granite Vision 2B, Qwen2.5-VL-3B) oder über einen OpenAI-kompatiblen Endpunkt wie Ollama, Markdown-Ausgabe, CPU-Betrieb, Python 3.10–3.14, auch DOCX/PPTX | PyTorch und Modell-Downloads; Bildbeschreibung auf der CPU langsam |
| Marker 2.2.0 | Code Apache 2.0; Modellgewichte modifizierte OpenRAIL-M, kostenfrei nur für Forschung, private Nutzung und Unternehmen unter 5 Mio. USD Umsatz/Finanzierung | hohe Qualität und Geschwindigkeit, Tabellen, Formeln, Bildbeschreibung über `--use_llm` | Gewichtslizenz; Bildbeschreibung über LLM-Dienste mit Gemini als Standard, Ollama möglich |
| MinerU | eigene, Apache-2.0-basierte Lizenz ab 3.1 (zuvor AGPL) | stark bei wissenschaftlichen Dokumenten und Formeln, CPU-Pipeline | schwerer Stack; VLM-Backend benötigt eine GPU; Lizenz vor Nutzung prüfen |
| PyMuPDF4LLM | AGPL oder kommerziell (über PyMuPDF) | leicht und schnell, Markdown-Tabellen, automatische OCR über Tesseract | keine Bildbeschreibung; AGPL |
| olmOCR | Apache 2.0 | VLM überführt ganze Seiten in Text | NVIDIA-GPU mit mindestens 12 GB Speicher erforderlich |

Cloud-Dienste zur Dokumentanalyse widersprechen dem lokalen Ziel und werden nicht betrachtet.

**R-140 – Strukturierter PDF-Modus · muss · offen**
Ein dritter, ausdrücklich wählbarer Wert für `pdf_mode` (Arbeitstitel `structured`, CLI `--pdf-mode structured`) wandelt eine PDF lokal in strukturierten Text (Markdown) um. Dieser Text durchläuft danach unverändert dieselbe Textaufteilung, Generierung, Validierung, Duplikaterkennung, Unterdeck-Zuordnung und APKG-Ausgabe wie im Modus `local`. Der Modus funktioniert daher mit jedem Kartenmodell, auch mit reinen Textmodellen und lokal über Ollama. `local` bleibt Standard, `native` bleibt unverändert. Wie bei `native` gilt der Modus nur für `.pdf`; andere Formate werden mit einer verständlichen Meldung abgelehnt, bis R-153 umgesetzt ist.

**R-141 – Bewährte Bibliothek hinter eigenem Adapter · muss · offen**
Die Aufbereitung nutzt eine etablierte Open-Source-Bibliothek und wird nicht selbst entwickelt. Sie liegt hinter einer kleinen eigenen Schnittstelle in der Dokumentschicht (Eingabe: PDF-Pfad und Optionen; Ausgabe: `SourceDocument` mit Markdown-Text und einer Statistik), damit Bibliothek und Modelle austauschbar und Tests ohne die Bibliothek möglich bleiben. Auswahlkriterien: Lizenz ohne Copyleft- oder Umsatzbeschränkung für den Standardweg; Python 3.11 bis zur aktuell eingesetzten Version; Betrieb auf der CPU ohne Pflicht-GPU; lokal ausführbare Modelle; Tabellen, OCR, Bildbeschreibung und Markdown-Ausgabe. Vor der Implementierung werden die Kandidaten an einer kleinen Referenzsammlung verglichen (Folien mit Diagrammen, Tabellen, Formeln, gescannte Seiten, mehrspaltiger Text). Auswahl, Version, Quelle, Prüfdatum, Laufzeit und Speicherbedarf werden dokumentiert. Nach der Voruntersuchung ist Docling der bevorzugte Kandidat.

**R-142 – Text in Bildern und gescannte Seiten · muss · offen**
Seiten und Bildbereiche ohne verwertbare Textebene werden per Texterkennung (OCR) gelesen. Mindestens Deutsch und Englisch werden unterstützt; die Sprachen sind konfigurierbar. Eine vorhandene Textebene wird bevorzugt. OCR für alle Seiten kann ausdrücklich erzwungen werden, etwa bei einer fehlerhaften Textebene.

**R-143 – Abbildungen als Text · muss · offen**
Abbildungen wie Diagramme, Schaltpläne, Grafiken und Fotos werden von einem lokal laufenden Bild-Sprach-Modell sachlich beschrieben: dargestellter Inhalt, Beschriftungen, Achsen, Werte und Beziehungen, ohne Vermutungen. Die Beschreibung steht an der Stelle der Abbildung im Text und ist eindeutig als maschinelle Beschreibung mit Seitenzahl markiert, beispielsweise `[Abbildung S. 12 – Beschreibung: …]`. Text innerhalb der Abbildung wird zusätzlich per OCR übernommen. Das Kartenmodell erhält die Anweisung, dass solche Beschreibungen maschinell erstellt sind und keine darüber hinausgehenden Fakten erfunden werden dürfen. Das Beschreibungsmodell ist konfigurierbar: ein kleines eingebettetes Modell oder ein lokaler OpenAI-kompatibler Endpunkt wie Ollama. Die Bildbeschreibung kann ausdrücklich abgeschaltet werden; Abbildungen erscheinen dann nur als Platzhalter mit ihrem OCR-Text, und die Ausgabe weist darauf hin. Rein dekorative Elemente wie Logos sollen erkannt und ausgelassen werden.

**R-144 – Tabellen und Lesereihenfolge · muss · offen**
Tabellen werden mit Zeilen und Spalten als Markdown-Tabelle ausgegeben. Mehrspaltige Seiten erscheinen in natürlicher Lesereihenfolge. Überschriften bleiben als Markdown-Überschriften erhalten, damit Kapitelstruktur und Unterdeck-Zuordnung (R-131) davon profitieren. Wiederkehrende Kopf- und Fußzeilen sollen entfernt werden. Die Textaufteilung (R-012) soll Tabellen und Abbildungsbeschreibungen nicht trennen, solange sie in einen Abschnitt passen.

**R-145 – Formeln · soll · offen**
Formeln werden als LaTeX erkannt und in den Text übernommen. Die Formelerkennung ist abschaltbar, weil sie die Aufbereitung deutlich verlangsamt.

**R-146 – Vollständigkeit und kein stiller Verlust · muss · offen**
Jede Seite ist im Ergebnis mit einem Seitenmarker `[Seite N]` vertreten. Nach der Aufbereitung meldet die CLI die Zahl der Seiten, der per OCR gelesenen Seiten, der Tabellen, der beschriebenen und der ausgelassenen Abbildungen sowie der Formeln. Kann ein Element nicht gelesen oder beschrieben werden, bricht der Lauf mit einer verständlichen Meldung ab; nur mit einer ausdrücklichen Option wird stattdessen ein gemeldeter Platzhalter `[nicht lesbar: …]` eingefügt. Ist die Aufbereitung nicht installiert oder nicht lauffähig, wird nicht stillschweigend auf `local` oder `native` gewechselt (vgl. R-123).

**R-147 – Lokal und privat · muss · offen**
Während der Aufbereitung verlassen weder die PDF noch Seiten- oder Abbildungsbilder den Rechner. Ein Beschreibungsendpunkt auf einem anderen Rechner erfordert eine ausdrückliche Option und wird in Hilfe, Profil und Dokumentation wie `native` als Datenübertragung gekennzeichnet. An das Kartenmodell geht nur der aufbereitete Text. Benötigte Modelle werden ausschließlich aus den dokumentierten Quellen der Bibliothek geladen; der erste Download wird angekündigt. Danach muss die Aufbereitung offline funktionieren; ein lokales Modellverzeichnis ist konfigurierbar.

**R-148 – Optionale Installation und Ressourcen · muss · offen**
Die Abhängigkeiten der Aufbereitung (Bibliothek, PyTorch, Modelle) sind ein optionales Paket-Extra, beispielsweise `pip install -e '.[pdf]'`. Basisinstallation, `local` und `native` bleiben schlank und unverändert. Fehlt das Extra, meldet `generate` vor jeder Verarbeitung den Installationsbefehl. Ein Fortschritt je Seite wird angezeigt. Laufzeit, Arbeitsspeicher- und Plattenbedarf, Modellgrößen und die optionale GPU-Nutzung werden dokumentiert.

**R-149 – Konfiguration · muss · offen**
Der Modus und seine Optionen – OCR-Sprachen, erzwungene OCR, Bildbeschreibung an oder aus, Beschreibungsmodell beziehungsweise Endpunkt, Formelerkennung, Platzhalter statt Abbruch – sind im YAML-Profil streng validiert konfigurierbar und, soweit für die Bedienung nötig, per CLI überschreibbar. Es gelten die bestehende Priorität (R-115) sowie positive und negative Formen boolescher Optionen. `config show` zeigt die wirksamen Werte und ihre Herkunft.

**R-150 – Aufbereiteten Text prüfen und wiederverwenden · soll · offen**
Der aufbereitete Text kann als Markdown-Datei gespeichert werden, atomar und ohne vorhandene Dateien zu überschreiben. So lässt sich die Vollständigkeit prüfen und von Hand korrigieren. Die Datei kann wie jede Markdown-Datei mit `generate` erneut verarbeitet werden, ohne die Aufbereitung zu wiederholen.

**R-151 – Tests · muss · offen**
Reguläre Tests ersetzen Bibliothek und Modelle durch Attrappen. Sie prüfen Moduswahl und Priorität, die Markierung von Seiten, Abbildungen und Tabellen, Abbruch und Platzhalter, ein fehlendes Extra, das Ausbleiben eines stillen Fallbacks und jeder Übertragung, die unveränderte Weiterverarbeitung des Textes und das Speichern des Zwischentextes. Ein Integrationstest mit der echten Bibliothek und einer kleinen erzeugten PDF ist gesondert markiert und läuft nicht im Standardlauf.

**R-152 – Dokumentation · muss · offen**
README, Benutzerhandbuch, Entwicklerhandbuch, CLI-Hilfe und `config.example.yaml` beschreiben Installation, Modus, Optionen, Modell-Downloads, Datenschutz, Ressourcenbedarf und Grenzen, insbesondere dass Abbildungsbeschreibungen fehlerhaft sein können.

**R-153 – Weitere Formate · kann · später**
Dieselbe Aufbereitung für DOCX und PPTX mit eingebetteten Bildern sowie für Bilddateien (PNG, JPEG) als Eingabe.

**R-154 – Zwischenspeicher · kann · später**
Aufbereitete Dokumente werden anhand eines Datei-Hashes zwischengespeichert, damit wiederholte Läufe die Aufbereitung überspringen.

## 13. Spätere Erweiterungen

Die folgenden Punkte sind Ideen und keine aktuellen Implementierungsaufträge:

- **R-200 · kann · später:** Webinterface beziehungsweise Web-API auf dem vorhandenen fachlichen Kern; Konfiguration und Kartenprüfung über dieselben Dienste.
- **R-201 · kann · später:** Linux-Container und Deployment auf Proxmox, erst nach stabiler Anwendung und geklärter Verwaltung von Konfiguration, Secrets und Daten.
- **R-202 · kann · später:** URLs als zusätzliche Quelle mit eigenen Sicherheits- und Datenschutzregeln.
- **R-203 · übernommen in R-142:** OCR für gescannte PDF-Dokumente; weitere Formate siehe R-153.
- **R-204 · kann · später:** Quellenangaben pro Karte, interaktive Prüfung und Fortsetzen abgebrochener Generierungen.
- **R-205 · kann · später:** Lückentext, weitere Notiztypen sowie Bilder und Audio in Karten.

## 14. Aktuelle CLI-Vertragsgrundlage

Bis zur Umsetzung der neuen Konfigurations- und Hilfeanforderungen bestehen diese Befehle:

- `generate EINGABE [--output ZIEL.apkg] [--deck NAME] [--model PROVIDER/MODELL] [--profile NAME] [--limit N] [--extend/--no-extend] [--subdecks/--no-subdecks] [--json DATEI] [--config DATEI] [--pdf-mode local|native]`
- `export KARTEN.json [--output ZIEL.apkg] [--deck NAME] [--extend/--no-extend] [--config DATEI]`
- `decks PAKET.apkg`
- `config show EINGABE [--config DATEI] [weitere Overrides]`

Wichtige Ist-Eigenschaften:

- `--output` ist erforderlich, sofern kein `output_dir` in YAML konfiguriert ist; dann wird der Dateiname aus der Eingabe abgeleitet.
- `--deck` ist bei `generate` optional; bei `export` kann stattdessen `generation.deck` aus YAML verwendet werden.
- `--config` beziehungsweise `ANKI_CONFIG` wählt YAML; ohne Datei bleibt der bisherige Workflow erhalten.
- `config show` gibt effektive Werte und Herkunft ohne geheime Schlüsselwerte als JSON aus.
- `--pdf-mode native` beziehungsweise ein natives Profil lädt Original-PDFs nur für ausdrücklich freigegebene OpenAI-Modelle hoch; `local` bleibt Standard.
- Ohne `--extend` muss die Ausgabedatei neu sein; mit `--extend` muss sie bereits existieren.
- Fehlende Elternordner der Ausgabe werden erstellt.
- `--limit` akzeptiert nichtnegative ganze Zahlen; `0` bedeutet Unlimited.
- API-Schlüssel werden über die in YAML referenzierten provider-spezifischen Umgebungsvariablen aus `.env` oder der Prozessumgebung bereitgestellt; `.env` enthält keine Modelle oder Endpunkte.

## 15. Abnahmekriterien für die noch offenen Hauptpakete

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

### D. Unterdeck-Paket (req-4)

1. Der Unterdeck-Modus ist standardmäßig aus und wird über CLI oder YAML ausdrücklich aktiviert; ohne ihn bleibt das Verhalten unverändert.
2. Generierte Karten landen in `Deck::Unterdeck`; Unterdecknamen sind validiert und innerhalb eines Laufs konsistent.
3. Beim Erweitern werden vorhandene Unterdecks mit Beispielfragen als Kontext übergeben und bevorzugt wiederverwendet; das Lesen verändert das Paket nicht.
4. Duplikate werden über das übergeordnete Deck und alle Unterdecks erkannt; Lernstände bleiben erhalten.
5. JSON-Export, nativer Weg, Konfiguration und Diagnose unterstützen den Modus.
6. Alle Tests laufen ohne echte KI-Aufrufe; README und beide Handbücher sind aktualisiert.

### E. PDF-Aufbereitungspaket (req-5)

1. Die Bibliotheksauswahl ist an einer Referenzsammlung begründet und mit Version, Lizenz, Quelle, Prüfdatum und Messwerten dokumentiert.
2. Der strukturierte Modus wird nur ausdrücklich aktiviert; `local`, `native` und die Basisinstallation bleiben unverändert.
3. In der Referenzsammlung ist jede Seite im Text vertreten; Text in Bildern ist per OCR enthalten, Tabellen erscheinen als Markdown-Tabellen und Abbildungen als markierte Beschreibungen.
4. Nicht lesbare Elemente werden gemeldet; es gibt keinen stillen Verlust und keinen stillen Moduswechsel.
5. Während der Aufbereitung werden keine Dokumentdaten übertragen; nach dem ersten Modell-Download funktioniert sie offline.
6. Der aufbereitete Text durchläuft dieselbe Validierung, Unterdeck-Zuordnung und APKG-Ausgabe wie im Modus `local`.
7. Reguläre Tests laufen ohne Bibliothek, Modelle und Netzwerk; README und beide Handbücher sind aktualisiert.
