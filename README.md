# EcoVolter pro Home Assistant

**Čeština** | [English](README.en.md)

Vlastní integrace EcoVolter pro Home Assistant využívající lokální API nabíječky.

> **Aktuální vydání:** v0.2.1. Integrace komunikuje lokálně s EcoVolterem a obsahuje vlastní kartu pro Home Assistant.

## Funkce

- Lokální komunikace bez nutnosti cloudu
- Podpora více nabíječek EcoVolter
- Nastavení pomocí IP adresy nebo hostname
- Překlad hostname → IP s uložením IP pro rychlou komunikaci
- Obnovení DNS každých 60 minut a okamžité nové přeložení při chybě spojení
- Stav nabíjení a informace o připojeném vozidle
- Aktuální výkon a energie aktuální nabíjecí relace
- Celkově nabitá energie, počet nabíjení a celková doba nabíjení
- Proud a napětí jednotlivých fází
- Povolení a zakázání nabíjení
- Přepínání jednofázového / třífázového režimu
- Nastavení nabíjecího proudu 6–16 A
- České a anglické rozhraní v Home Assistantu
- Vlastní EcoVolter karta: Minimalistic / Compact / Detailed, výběr nabíječky a CZ/EN
- Živá telemetrie s obnovou stavu každou 1 s
- Nastavení nabíječky načítané odděleně a ovládané přes PATCH
- Serializace API požadavků pro stabilnější komunikaci

Integrace používá lokální API EcoVolteru pro získávání stavu, diagnostických údajů a nastavení nabíječky.

## Instalace pro testování

Zkopírujte složku:

`custom_components/ecovolter`

do:

`/config/custom_components/ecovolter`

Poté restartujte Home Assistant a otevřete **Nastavení → Zařízení a služby → Přidat integraci**. Vyhledejte **EcoVolter**.

Při konfiguraci zadejte:

- IP adresu nebo hostname nabíječky
- tajný klíč Local API

**API tajný klíč nikdy nezveřejňujte.** Ukládá se do konfigurace Home Assistantu, nikoliv do tohoto repozitáře.

## Hostname / DNS

Pokud zadáte hostname, integrace jej přeloží na IP adresu a tuto IP uloží do cache. Běžná komunikace s API následně probíhá přímo přes IP adresu, aby byla co nejrychlejší.

Hostname se znovu překládá každých 60 minut. Pokud komunikace se zapamatovanou IP selže kvůli síťové chybě, integrace okamžitě provede nový DNS překlad a požadavek jednou zopakuje.

Chyba autentizace nevyvolává nový DNS překlad.

## EcoVolter karta

Integrace registruje vlastní kartu **EcoVolter**, kterou lze přidat přes běžný editor dashboardu. V editoru karty lze vybrat konkrétní nabíječku, variantu **Minimalistic**, **Compact** nebo **Detailed**, vlastní název a jazyk **Čeština / English**.

Karta zobrazuje výkon, energii relace, počet aktivních fází a nastavený nabíjecí proud. Umožňuje zapnout/vypnout nabíjení, přepnout 1/3 fáze a nastavit proud 6–16 A. Pro ovládání proudu lze v editoru zvolit slider nebo kompaktní ovládání **− / hodnota / +** s možností ručního zadání. Minimalistic varianta zobrazuje základní údaje přímo ve stavovém řádku, Detailed varianta navíc proud L1–L3, napětí L1–L3 a dlouhodobé statistiky.

## Dashboard příklady

V repozitáři jsou také tři hotové příklady postavené pouze na nativních kartách Home Assistantu:

- `examples/lovelace/compact.yaml` – kompaktní karta pro běžné ovládání
- `examples/lovelace/detailed.yaml` – detailní karta včetně fází a statistik
- `examples/lovelace/dual-charger.yaml` – přehled pro dvě nabíječky

Konkrétní ID entit závisí na názvu zařízení vytvořeném v Home Assistantu. V ukázkách proto nahraďte vzorová ID vlastními ID entit.

## Poznámky

EcoVolter a jeho lokální API jsou produkty/služby třetí strany. Tento projekt je nezávislá integrace pro Home Assistant a není oficiálně spojen s výrobcem.

Automatizace v Home Assistantu nenahrazují elektrické jištění ani jiné bezpečnostní prvky elektroinstalace.

## Licence

MIT © 2026 IT síť s.r.o.
