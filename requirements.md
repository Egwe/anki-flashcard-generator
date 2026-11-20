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

**R-013 – OCR · muss · umgesetzt über R-142**
Im Modus `local` benötigen gescannte PDFs ohne Textebene weiterhin eine externe OCR. Seit req-5 bietet der strukturierte PDF-Modus eine eingebaute OCR (R-142); der Modus `local` bleibt bei der eingebetteten Textebene.

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

Ziel aus [req-5.md](./req-5.md): Auch PDFs mit vielen Abbildungen, Diagrammen und Tabellen – typisch für Vorlesungsfolien und Skripte – sollen ohne Informationsverlust in Karten einfließen. Dazu wird die PDF lokal so vollständig wie möglich in Text umgewandelt; an das Kartenmodell geht danach nur noch Text. Für die Umwandlung werden vorhandene Open-Source-Werkzeuge genutzt, die selbst lokale KI-Modelle für Layout, Tabellen, Texterkennung und Bilder einsetzen. Das Problem wird nicht von Grund auf neu gelöst. Das Bildmodell, das Abbildungen beschreibt, muss austauschbar sein: lokal eingebettet, über ein Modellprofil wie das Kartenmodell oder über eine eigene API.

**Kernproblem.** Der Modus `local` liest mit pypdf nur die eingebettete Textebene. Dabei geht verloren:

- Text, der nur als Bild vorliegt: gescannte Seiten, Screenshots, als Bild eingefügte Folieninhalte;
- Information, die nur grafisch dargestellt ist: Diagramme, Schaltpläne, Abbildungen samt Achsen und Beschriftungen;
- die Struktur von Tabellen: Zellen werden zu Fließtext ohne Zeilen- und Spaltenbezug;
- Formeln, deren Symbole, Hoch- und Tiefstellungen in der Textebene oft verstümmelt sind;
- die Lesereihenfolge bei mehrspaltigem Layout sowie die Trennung von Kopf- und Fußzeilen.

Seiten ohne Textebene werden heute stillschweigend übersprungen; nur ein vollständig textloses Dokument führt zu einem Fehler. Der Modus `native` (Abschnitt 10) gibt dem Modell zusätzlich Seitenbilder, funktioniert aber nur für geprüfte OpenAI-Modelle, überträgt die Originaldatei und steht lokalen Textmodellen nicht zur Verfügung.

**Machbarkeit.** Text, Lesereihenfolge, Tabellen und Texterkennung sind mit etablierten Bibliotheken zuverlässig und auf einer normalen CPU lösbar. Formeln sind lösbar, verlangsamen die Aufbereitung aber deutlich. Abbildungen lassen sich nur annähernd in Text übersetzen: Die Beschreibung stammt von einem Bild-Sprach-Modell (VLM), ihre Qualität hängt stark von dessen Größe ab, und sie kann Fehler enthalten. Kleine Modelle laufen auf der CPU, liefern aber eher kurze Bildunterschriften; für technische Diagramme sind größere Modelle über einen lokalen Endpunkt wie Ollama oder auf einer GPU realistisch. „Vollständig“ bedeutet daher: Jede Seite und jedes Element ist im Text vertreten oder als nicht lesbar gemeldet – nicht, dass jede grafische Information verlustfrei übertragen wird. Der Preis sind schwere optionale Abhängigkeiten (PyTorch, Modelldateien von einigen hundert MB bis zu mehreren GB) und Laufzeiten im Bereich von Sekunden pro Seite statt Millisekunden, mit Bildbeschreibung auf der CPU auch deutlich mehr.

**Entscheidung** (20.11.2026): Die Aufbereitung wird mit **Docling** umgesetzt (R-141). Grundlage war diese Voruntersuchung (Quellen: offizielle Projektseiten, READMEs und PyPI):

| Kandidat | Lizenz | Stärken | Einschränkungen |
|---|---|---|---|
| Docling 2.151.1 | MIT | Layoutanalyse, Tabellenstruktur (TableFormer), OCR (u. a. RapidOCR, EasyOCR, Tesseract), Formeln als LaTeX, Bildbeschreibung mit lokalen VLMs (SmolVLM-256M, Granite Vision 2B, Qwen2.5-VL-3B) oder über einen OpenAI-kompatiblen Endpunkt wie Ollama, Markdown-Ausgabe, CPU-Betrieb, Python 3.10–3.14, auch DOCX/PPTX | PyTorch und Modell-Downloads; Bildbeschreibung auf der CPU langsam |
| Marker 2.2.0 | Code Apache 2.0; Modellgewichte modifizierte OpenRAIL-M, kostenfrei nur für Forschung, private Nutzung und Unternehmen unter 5 Mio. USD Umsatz/Finanzierung | hohe Qualität und Geschwindigkeit, Tabellen, Formeln, Bildbeschreibung über `--use_llm` | Gewichtslizenz; Bildbeschreibung über LLM-Dienste mit Gemini als Standard, Ollama möglich |
| MinerU | eigene, Apache-2.0-basierte Lizenz ab 3.1 (zuvor AGPL) | stark bei wissenschaftlichen Dokumenten und Formeln, CPU-Pipeline | schwerer Stack; VLM-Backend benötigt eine GPU; Lizenz vor Nutzung prüfen |
| PyMuPDF4LLM | AGPL oder kommerziell (über PyMuPDF) | leicht und schnell, Markdown-Tabellen, automatische OCR über Tesseract | keine Bildbeschreibung; AGPL |
| olmOCR | Apache 2.0 | VLM überführt ganze Seiten in Text | NVIDIA-GPU mit mindestens 12 GB Speicher erforderlich |

Cloud-Dienste zur Dokumentanalyse widersprechen dem lokalen Ziel und werden nicht betrachtet.

**R-140 – Strukturierter PDF-Modus · muss · umgesetzt**
Ein dritter, ausdrücklich wählbarer Wert `pdf_mode: structured` (CLI `--pdf-mode structured`) wandelt eine PDF lokal in strukturierten Text (Markdown) um. Die Kartenanfragen selbst enthalten nur diesen Text. Dieser Text durchläuft danach unverändert dieselbe Textaufteilung, Generierung, Validierung, Duplikaterkennung, Unterdeck-Zuordnung und APKG-Ausgabe wie im Modus `local`. Der Modus funktioniert daher mit jedem Kartenmodell, auch mit reinen Textmodellen und lokal über Ollama. `local` bleibt Standard, `native` bleibt unverändert. Wie bei `native` gilt der Modus nur für `.pdf`; andere Formate werden mit einer verständlichen Meldung abgelehnt, bis R-153 umgesetzt ist.

**R-141 – Docling hinter eigenem Adapter · muss · umgesetzt**
Die Aufbereitung verwendet Docling (MIT-Lizenz) und wird nicht selbst entwickelt. Docling liegt hinter einer kleinen eigenen Schnittstelle in der Dokumentschicht (Eingabe: PDF-Pfad und Optionen; Ausgabe: `SourceDocument` mit Markdown-Text und einer Statistik). So bleiben Tests ohne Docling möglich, und Docling-Typen gelangen nicht in Generierung, CLI oder APKG-Schicht. Die unterstützte Docling-Version wird im optionalen Extra mit Unter- und Obergrenze festgelegt. Vor der Umsetzung wird Docling an einer kleinen Referenzsammlung geprüft (Folien mit Diagrammen, Tabellen, Formeln, gescannte Seiten, mehrspaltiger Text). Dabei werden OCR-Engine, Tabellenmodus und das Standard-Bildmodell festgelegt. Version, Quelle, Prüfdatum, Laufzeit und Speicherbedarf werden dokumentiert.

*Prüfergebnis (20.11.2026, Docling 2.151.1, PyTorch 2.15 CPU, an den Vorlesungs-PDFs in `input/`):* OCR-Engine RapidOCR mit PyTorch-Backend (EasyOCR ausgeschlossen, weil es nach `~/.EasyOCR` schreibt), TableFormer im Modus *accurate*, Bildausschnitte mit Faktor 2, Standard-Bildmodell SmolVLM-256M-Instruct ohne Bildkachelung. Messwerte und Grenzen stehen in README und Entwicklerhandbuch. SmolVLM-256M und -500M beschrieben technische Abbildungen unzuverlässig; SmolVLM2-2.2B überschritt den verfügbaren Arbeitsspeicher. Die Bildbeschreibung über ein Profil ist nur mit simulierten Antworten geprüft, nicht mit einem echten Vision-Modell. Auf der CPU war die Aufbereitung zu langsam (siehe R-158); ein Lauf auf einer GPU steht noch aus.

**R-142 – Text in Bildern und gescannte Seiten · muss · umgesetzt**
Seiten und Bildbereiche ohne verwertbare Textebene werden per Texterkennung (OCR) gelesen. Mindestens Deutsch und Englisch werden unterstützt; die Sprachen sind konfigurierbar. Eine vorhandene Textebene wird bevorzugt. OCR für alle Seiten kann ausdrücklich erzwungen werden, etwa bei einer fehlerhaften Textebene.

**R-143 – Abbildungen als Text · muss · umgesetzt**
Abbildungen wie Diagramme, Schaltpläne, Grafiken und Fotos werden von einem Bild-Sprach-Modell (Bildmodell, R-155) sachlich beschrieben: dargestellter Inhalt, Beschriftungen, Achsen, Werte und Beziehungen, ohne Vermutungen. Die Beschreibung steht an der Stelle der Abbildung im Text und ist eindeutig als maschinelle Beschreibung mit Seitenzahl markiert, beispielsweise `[Abbildung S. 12 – Beschreibung: …]`. Text innerhalb der Abbildung wird zusätzlich per OCR übernommen. Das Kartenmodell erhält die Anweisung, dass solche Beschreibungen maschinell erstellt sind und keine darüber hinausgehenden Fakten erfunden werden dürfen. Welches Bildmodell beschreibt, ist austauschbar (R-155, R-156); Standard ist ein lokal eingebettetes Modell. Die Bildbeschreibung kann ausdrücklich abgeschaltet werden; Abbildungen erscheinen dann nur als Platzhalter mit ihrem OCR-Text, und die Ausgabe weist darauf hin. Rein dekorative Elemente wie Logos sollen erkannt und ausgelassen werden.

**R-144 – Tabellen und Lesereihenfolge · muss · umgesetzt**
Tabellen werden mit Zeilen und Spalten als Markdown-Tabelle ausgegeben. Mehrspaltige Seiten erscheinen in natürlicher Lesereihenfolge. Überschriften bleiben als Markdown-Überschriften erhalten, damit Kapitelstruktur und Unterdeck-Zuordnung (R-131) davon profitieren. Wiederkehrende Kopf- und Fußzeilen sollen entfernt werden. Die Textaufteilung (R-012) soll Tabellen und Abbildungsbeschreibungen nicht trennen, solange sie in einen Abschnitt passen.

**R-145 – Formeln · soll · umgesetzt**
Formeln werden als LaTeX erkannt und in den Text übernommen. Die Formelerkennung ist abschaltbar, weil sie die Aufbereitung deutlich verlangsamt.

**R-146 – Vollständigkeit und kein stiller Verlust · muss · umgesetzt**
Jede Seite ist im Ergebnis mit einem Seitenmarker `[Seite N]` vertreten. Nach der Aufbereitung meldet die CLI die Zahl der Seiten, der per OCR gelesenen Seiten, der Tabellen, der beschriebenen und der ausgelassenen Abbildungen sowie der Formeln. Kann ein Element nicht gelesen oder beschrieben werden, bricht der Lauf mit einer verständlichen Meldung ab; nur mit einer ausdrücklichen Option wird stattdessen ein gemeldeter Platzhalter `[nicht lesbar: …]` eingefügt. Ist die Aufbereitung nicht installiert oder nicht lauffähig, wird nicht stillschweigend auf `local` oder `native` gewechselt (vgl. R-123).

**R-147 – Lokal und privat · muss · umgesetzt**
Mit dem Standard-Bildmodell verlassen während der Aufbereitung weder die PDF noch Seiten- oder Abbildungsbilder den Rechner. Nur wenn ein Bildmodell über ein Modellprofil ausdrücklich gewählt ist (R-156), gehen Bildausschnitte – nie die ganze PDF – an den Provider dieses Profils. An das Kartenmodell geht in jedem Fall nur der aufbereitete Text. Benötigte Modelle werden ausschließlich aus den dokumentierten Quellen von Docling beziehungsweise des gewählten Modells geladen; der erste Download wird angekündigt. Danach muss die Aufbereitung offline funktionieren. Speicherort siehe R-157.

**R-148 – Optionale Installation und Ressourcen · muss · umgesetzt**
Die Abhängigkeiten der Aufbereitung (Docling, PyTorch) sind ein optionales Paket-Extra, beispielsweise `pip install -e '.[pdf]'`, das in die projekteigene `.venv` installiert wird. Modelle sind nicht Teil des Pakets, sondern werden nach R-157 im Projektordner abgelegt. Basisinstallation, `local` und `native` bleiben schlank und unverändert. Fehlt das Extra, meldet `generate` vor jeder Verarbeitung den Installationsbefehl. Ein Fortschritt je Seite wird angezeigt. Laufzeit, Arbeitsspeicher- und Plattenbedarf, Modellgrößen und die optionale GPU-Nutzung werden dokumentiert.

**R-149 – Konfiguration · muss · umgesetzt**
`pdf_mode: structured` ist wie die anderen PDF-Modi im Modellprofil und per CLI wählbar. Die Optionen der Aufbereitung hängen nicht vom Kartenmodell ab und stehen daher in einem eigenen, streng validierten YAML-Block (Arbeitstitel `pdf_conversion`): OCR-Sprachen, erzwungene OCR, Formelerkennung, Platzhalter statt Abbruch, Bildmodell-Backend mit Modell beziehungsweise Profil (R-155, R-156) und Modellordner (R-157). Mindestens Bildmodell-Backend, Bildprofil, erzwungene OCR, Formelerkennung und der Speicherpfad des Zwischentextes (R-150) sind per CLI überschreibbar. Es gelten die bestehende Priorität (R-115) sowie positive und negative Formen boolescher Optionen. `config show` zeigt die wirksamen Werte und ihre Herkunft.

**R-150 – Aufbereiteten Text prüfen und wiederverwenden · muss · umgesetzt**
Der aufbereitete Text kann als Markdown-Datei gespeichert werden, atomar und ohne vorhandene Dateien zu überschreiben. So lässt sich die Vollständigkeit prüfen und von Hand korrigieren. Die Datei kann wie jede Markdown-Datei mit `generate` erneut verarbeitet werden, ohne die Aufbereitung zu wiederholen.

**R-151 – Tests · muss · umgesetzt**
Reguläre Tests ersetzen Bibliothek und Modelle durch Attrappen. Sie prüfen Moduswahl und Priorität, die Markierung von Seiten, Abbildungen und Tabellen, Abbruch und Platzhalter, ein fehlendes Extra, das Ausbleiben eines stillen Fallbacks und jeder ungewollten Übertragung, alle Bildmodell-Backends samt Ablehnung von Profilen ohne freigegebene Bildeingabe, die Auflösung des Modellordners, die unveränderte Weiterverarbeitung des Textes und das Speichern des Zwischentextes. Ein Integrationstest mit echtem Docling, einem kleinen lokalen Bildmodell aus dem Projektordner und einer kleinen erzeugten PDF ist gesondert markiert und läuft nicht im Standardlauf.

**R-152 – Dokumentation · muss · umgesetzt**
README, Benutzerhandbuch, Entwicklerhandbuch, CLI-Hilfe und `config.example.yaml` beschreiben Installation, Modus, Optionen, Bildmodell-Backends mit Beispielprofilen, Modellordner und Modell-Downloads, Datenschutz, Ressourcenbedarf und Grenzen, insbesondere dass Abbildungsbeschreibungen fehlerhaft sein können.

**R-153 – Weitere Formate · kann · später**
Dieselbe Aufbereitung für DOCX und PPTX mit eingebetteten Bildern sowie für Bilddateien (PNG, JPEG) als Eingabe.

**R-154 – Zwischenspeicher · kann · später**
Aufbereitete Dokumente werden anhand eines Datei-Hashes im Modellordner nach R-157 zwischengespeichert, damit wiederholte Läufe die Aufbereitung überspringen.

**R-155 – Austauschbare Bildmodelle · muss · umgesetzt**
Docling liefert Layout, Bildausschnitte und deren Position im Text. Welches Modell eine Abbildung beschreibt, entscheidet ein austauschbares Backend hinter einer kleinen eigenen Schnittstelle (Eingabe: Bildausschnitt, Seitenzahl, Bildunterschrift beziehungsweise umgebender Text, Zielsprache; Ausgabe: Beschreibungstext). Alle Backends verwenden dieselbe Beschreibungsanweisung und dieselbe Markierung nach R-143. Weitere Backends lassen sich ergänzen, ohne Generierung, Kartenvalidierung, Unterdeck-Zuordnung oder APKG-Ausgabe zu ändern. Vorgesehen sind:

- `local` (Standard): ein lokal im Prozess laufendes Bildmodell, wählbar über eine Docling-Voreinstellung oder eine beliebige Hugging-Face-Modellkennung;
- `profile`: ein Modellprofil aus der YAML-Konfiguration nach R-156;
- `none`: keine Beschreibung, nur Platzhalter mit OCR-Text nach R-143.

**R-156 – Bildmodell über ein Modellprofil · muss · umgesetzt**
Das Bildmodell kann über dieselben Modellprofile angesprochen werden wie das Kartenmodell: entweder über dasselbe Profil, das die Karten erzeugt, oder über ein eigenes, benanntes Profil, etwa ein Vision-Modell in Ollama auf einem Server, einen anderen API-Anbieter oder einen eigenen OpenAI-kompatiblen Endpunkt. Es gelten dasselbe `provider/modell`-Format über LiteLLM, `api_base`, `api_key_env`, Timeout und Optionen; Schlüssel kommen ausschließlich aus der Umgebung. Weil Fähigkeiten nicht am Modellnamen erraten werden dürfen, muss ein für Bilder genutztes Profil die Bildeingabe ausdrücklich freigeben (Arbeitstitel `image_input: true`); sonst bricht der Lauf vor der Aufbereitung verständlich ab. Bei diesem Backend kündigt die CLI vor der Aufbereitung an, dass Bildausschnitte an Provider und Modell des Profils gesendet werden; Hilfe, Profil und Dokumentation kennzeichnen das wie `native` als Datenübertragung. `config.example.yaml` enthält ein kommentiertes Beispielprofil für ein lokales Vision-Modell.

**R-157 – Modelle und Caches im Projektordner · muss · umgesetzt**
Alles, was die Aufbereitung herunterlädt oder zwischenspeichert – Docling-Modelle, OCR- und Bildmodelle sowie die Caches von Hugging Face und PyTorch –, liegt in einem einzigen, gut auffindbaren Modellordner, standardmäßig `models/` neben der YAML-Konfiguration und damit im Projektordner. Ohne YAML-Datei gilt `models/` im aktuellen Arbeitsverzeichnis. Der Pfad ist in YAML konfigurierbar; relative YAML-Pfade werden wie in R-113 relativ zur YAML-Datei aufgelöst. Die Anwendung setzt die Speicherorte der Bibliotheken für ihren eigenen Prozess selbst und schreibt nichts in benutzerweite Ordner wie `~/.cache/huggingface`, `~/.cache/torch` oder `~/.EasyOCR`. Die dokumentierte Installation verwendet die projekteigene `.venv` und keinen globalen pip-Cache. Der Modellordner steht in `.gitignore` und wird nie committet. Die CLI nennt den verwendeten Ordner beim ersten Download. Ein Befehl soll die benötigten Modelle vorab in diesen Ordner laden, damit danach offline gearbeitet werden kann. Modelle, die ein separater Dienst wie Ollama verwaltet, bleiben in dessen eigener Ablage; das wird dokumentiert.


**R-158 – GPU als Voraussetzung · muss · umgesetzt**
Der strukturierte Modus ist für einen GPU-Beschleuniger ausgelegt: NVIDIA über CUDA, AMD über eine ROCm-Version von PyTorch, Apple Silicon über MPS oder Intel über XPU. Vor Modell-Downloads und Aufbereitung prüft das Programm, ob PyTorch einen solchen Beschleuniger nutzen kann, und verwendet ihn für Docling und das lokale Bildmodell. Ohne Beschleuniger bricht der Lauf mit einer klaren Meldung ab. Sie nennt die beiden Alternativen: Entweder übernimmt das KI-Modell die PDF (`--pdf-mode native`, Upload an einen freigegebenen Provider), oder `--pdf-mode local` liest nur die eingebettete Textebene. Es gibt keinen stillen Wechsel des Modus. Eine ausdrückliche Option (`--allow-cpu`, YAML `pdf_conversion.allow_cpu`, Standard aus) erlaubt den CPU-Betrieb trotzdem, etwa für kurze Dokumente oder mit `--no-formulas`; die CLI weist dann auf die lange Laufzeit hin. Begründung (Messung 20.11.2026): Auf einem Laptop mit Ryzen 5 PRO 4650U ohne nutzbare GPU brauchte die Aufbereitung einer 15-seitigen Vorlesung mit Formelerkennung über 50 Minuten. Die integrierte Radeon-Vega-GPU (`gfx90c`) wird von ROCm nicht offiziell unterstützt und hat nur 512 MiB eigenen Speicher.
## 13. Vorbereitung der Web-Oberfläche „Anki Studio“

Entscheidung vom 20.11.2026: Die Web-Oberfläche entsteht als eigenes Projekt „Anki Studio“ in einem eigenen Repository. Sie bindet dieses Paket als versionierte Python-Abhängigkeit ein und ist ein weiterer Client des selbst betriebenen Anki-Sync-Servers. Dieses Repository liefert dafür nur den UI-unabhängigen Kern. Web-Oberfläche, Sync, Authentifizierung und Deployment gehören nicht hierher. Die Übergabe an das neue Projekt beschreibt [docs/anki-studio-uebergabe.md](./docs/anki-studio-uebergabe.md).

**R-170 – Generierungsdienst ohne CLI · muss · umgesetzt**
Die Abläufe von `generate`, `export` und `models download` müssen als UI-unabhängiger Dienst aufrufbar sein: Ausgabe prüfen, Unterdeck-Kontext lesen, Karten im gewählten PDF-Modus erzeugen, JSON schreiben und Paket schreiben. Der Dienst importiert weder Typer noch Rich und gibt nichts auf der Konsole aus. Die CLI wird zu einer dünnen Schicht, die Optionen sammelt, den Dienst aufruft und Ereignisse darstellt. Ihr Verhalten, ihre Ausgaben und ihre Exit-Codes bleiben unverändert.

**R-171 – Fortschritts- und Hinweisereignisse · muss · umgesetzt**
Der Dienst meldet Fortschritt und Hinweise als strukturierte, unveränderliche Ereignisse an einen vom Aufrufer übergebenen Callback: Beginn und Fortschritt einer Phase (Aufbereitung, Generierung), Hinweise mit Stufe (Information, Warnung, Datenübertragung) und die Statistik der strukturierten Aufbereitung. Die Ereignisse lassen sich ohne Verlust in JSON umwandeln, damit eine Web-Oberfläche sie live übertragen kann. Ankündigungen von Datenübertragungen (native PDF, Bild-Profil) sind als eigene Stufe erkennbar.

**R-172 – Abbruch · soll · umgesetzt**
Ein Aufrufer kann einen laufenden Generierungsauftrag abbrechen. Der Dienst prüft eine Abbruchanfrage zwischen Abschnitten der KI-Generierung und zwischen Schritten der Aufbereitung und bricht dann mit einem eigenen Fehler ab. Ein abgebrochener Lauf schreibt weder JSON noch Paket. Ein einzelner laufender Provider-Request oder ein nativer Upload wird nicht unterbrochen; der Abbruch greift danach.

**R-173 – Karten erzeugen und Ziel schreiben getrennt · muss · umgesetzt**
Karten erzeugen und Karten schreiben sind getrennt aufrufbar. Eine Oberfläche kann Karten erzeugen, sie anzeigen und bearbeiten lassen und erst danach in ein Ziel schreiben. Für die geprüften Karten gelten dieselbe Validierung, Duplikaterkennung und Escaping-Regeln wie im direkten Lauf.

**R-174 – Ziel Anki-Sammlung · muss · umgesetzt**
Zusätzlich zur APKG-Datei kann eine vom Aufrufer geöffnete Anki-Sammlung (offizielles `anki.collection.Collection`-Objekt) Ziel sein. Es gelten derselbe Notiztyp, dieselbe Duplikaterkennung über Deck und Unterdecks, dieselben stabilen GUIDs, dasselbe HTML-Escaping und dieselbe Unterdeck-Logik wie beim Erweitern eines Pakets. Alle neuen Notizen eines Aufrufs werden in einer einzigen Anki-Operation hinzugefügt. Decks mit Kartenanzahl und der Unterdeck-Kontext lassen sich ebenso aus einer offenen Sammlung lesen. Das Paket öffnet, synchronisiert oder schließt keine Sammlung selbst; Pfad, Sperren und Sync verantwortet der Aufrufer. Die CLI bleibt bei APKG-Dateien und berührt keine persönliche Sammlung.

**R-175 – Versionierte Schnittstelle · muss · umgesetzt**
Die von Anki Studio genutzten Funktionen und Klassen sind im Entwicklerhandbuch als öffentliche Schnittstelle beschrieben. Der Stand, der sie erstmals bereitstellt, erhält die Paketversion 0.2.0 und den Git-Tag `v0.2.0`. Spätere inkompatible Änderungen dieser Schnittstelle erhöhen die Version und werden in der Übergabedatei vermerkt.

**R-176 – Übergabe an Anki Studio · muss · umgesetzt**
[docs/anki-studio-uebergabe.md](./docs/anki-studio-uebergabe.md) bündelt Ziel, Entscheidungen, Infrastruktur, Architektur, Anforderungen an Anki Studio, Risiken und die konkreten Schnittstellen dieses Pakets. Sie wird aktualisiert, sobald R-170 bis R-175 umgesetzt sind.

## 14. Spätere Erweiterungen

Die folgenden Punkte sind Ideen und keine aktuellen Implementierungsaufträge:

- **R-200 · übertragen an Anki Studio:** Webinterface beziehungsweise Web-API auf dem vorhandenen fachlichen Kern; Konfiguration und Kartenprüfung über dieselben Dienste. Umsetzung im eigenen Repository, vorbereitet durch R-170 bis R-176.
- **R-201 · übertragen an Anki Studio:** Linux-Container und Deployment auf Proxmox. Umsetzung im eigenen Repository; siehe [docs/anki-studio-uebergabe.md](./docs/anki-studio-uebergabe.md).
- **R-202 · kann · später:** URLs als zusätzliche Quelle mit eigenen Sicherheits- und Datenschutzregeln.
- **R-203 · übernommen in R-142:** OCR für gescannte PDF-Dokumente; weitere Formate siehe R-153.
- **R-204 · kann · später:** Quellenangaben pro Karte, interaktive Prüfung und Fortsetzen abgebrochener Generierungen.
- **R-205 · kann · später:** Lückentext, weitere Notiztypen sowie Bilder und Audio in Karten.

## 15. Aktuelle CLI-Vertragsgrundlage

Bis zur Umsetzung der neuen Konfigurations- und Hilfeanforderungen bestehen diese Befehle:

- `generate EINGABE [--output ZIEL.apkg] [--deck NAME] [--model PROVIDER/MODELL] [--profile NAME] [--limit N] [--extend/--no-extend] [--subdecks/--no-subdecks] [--json DATEI] [--config DATEI] [--pdf-mode local|structured|native] [--formulas/--no-formulas] [--force-ocr/--no-force-ocr] [--allow-unreadable/--no-allow-unreadable] [--picture-backend local|profile|none] [--picture-profile NAME] [--source-text DATEI.md]`
- `export KARTEN.json [--output ZIEL.apkg] [--deck NAME] [--extend/--no-extend] [--config DATEI]`
- `decks PAKET.apkg`
- `config show EINGABE [--config DATEI] [weitere Overrides]`
- `models download [--config DATEI] [--formulas/--no-formulas] [--picture-backend local|profile|none]`

Wichtige Ist-Eigenschaften:

- `--output` ist erforderlich, sofern kein `output_dir` in YAML konfiguriert ist; dann wird der Dateiname aus der Eingabe abgeleitet.
- `--deck` ist bei `generate` optional; bei `export` kann stattdessen `generation.deck` aus YAML verwendet werden.
- `--config` beziehungsweise `ANKI_CONFIG` wählt YAML; ohne Datei bleibt der bisherige Workflow erhalten.
- `config show` gibt effektive Werte und Herkunft ohne geheime Schlüsselwerte als JSON aus.
- `--pdf-mode native` beziehungsweise ein natives Profil lädt Original-PDFs nur für ausdrücklich freigegebene OpenAI-Modelle hoch; `local` bleibt Standard.
- `--pdf-mode structured` bereitet PDFs lokal mit Docling auf (optionales Extra `pdf`); Modelle und Caches liegen in `pdf_conversion.models_dir`.
- Ohne `--extend` muss die Ausgabedatei neu sein; mit `--extend` muss sie bereits existieren.
- Fehlende Elternordner der Ausgabe werden erstellt.
- `--limit` akzeptiert nichtnegative ganze Zahlen; `0` bedeutet Unlimited.
- API-Schlüssel werden über die in YAML referenzierten provider-spezifischen Umgebungsvariablen aus `.env` oder der Prozessumgebung bereitgestellt; `.env` enthält keine Modelle oder Endpunkte.

## 16. Abnahmekriterien für die noch offenen Hauptpakete

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

1. Docling ist an einer Referenzsammlung geprüft; Version, Lizenz, Quelle, Prüfdatum, Konfiguration und Messwerte sind dokumentiert.
2. Der strukturierte Modus wird nur ausdrücklich aktiviert; `local`, `native` und die Basisinstallation bleiben unverändert.
3. In der Referenzsammlung ist jede Seite im Text vertreten; Text in Bildern ist per OCR enthalten, Tabellen erscheinen als Markdown-Tabellen und Abbildungen als markierte Beschreibungen.
4. Nicht lesbare Elemente werden gemeldet; es gibt keinen stillen Verlust und keinen stillen Moduswechsel.
5. Das Bildmodell ist wählbar: lokal eingebettet, über das Kartenprofil, über ein eigenes Profil oder abgeschaltet. Profile ohne freigegebene Bildeingabe werden abgelehnt; ein weiteres Backend lässt sich ohne Änderungen an Generierung und Ausgabe ergänzen.
6. Mit dem lokalen Bildmodell werden keine Dokumentdaten übertragen; ein Profil-Bildmodell wird vor der Übertragung angekündigt. Nach dem ersten Modell-Download funktioniert die Aufbereitung offline.
7. Ohne GPU-Beschleuniger bricht der strukturierte Modus vor jeder Arbeit mit Hinweis auf `native` und `local` ab; nur `--allow-cpu` erlaubt den CPU-Betrieb.
8. Alle heruntergeladenen Modelle und Caches liegen im Modellordner im Projekt; nach Installation und Testlauf sind in benutzerweiten Cache-Ordnern keine neuen Daten entstanden.
9. Der aufbereitete Text durchläuft dieselbe Validierung, Unterdeck-Zuordnung und APKG-Ausgabe wie im Modus `local`.
10. Reguläre Tests laufen ohne Docling, Modelle, GPU und Netzwerk; README und beide Handbücher sind aktualisiert.

### F. Vorbereitung von Anki Studio

1. `generate`, `export` und `models download` laufen über einen Dienst ohne Typer, Rich und Konsolenausgabe; die bestehenden CLI-Tests bestehen unverändert in ihren Erwartungen.
2. Fortschritt, Hinweise, Datenübertragungen und Aufbereitungsstatistik kommen als JSON-fähige Ereignisse beim Aufrufer an.
3. Ein Abbruch zwischen Abschnitten oder Aufbereitungsschritten beendet den Lauf ohne geschriebene Dateien.
4. Karten lassen sich erzeugen, prüfen und danach in eine APKG-Datei oder eine offene Anki-Sammlung schreiben; die Sammlung erhält alle Notizen eines Aufrufs in einer Operation und mit denselben Duplikat-, GUID- und Unterdeckregeln.
5. Decks und Unterdeck-Kontext lassen sich aus einer offenen Sammlung lesen, ohne sie zu verändern.
6. Version 0.2.0 ist getaggt; Entwicklerhandbuch und Übergabedatei nennen die öffentliche Schnittstelle.
