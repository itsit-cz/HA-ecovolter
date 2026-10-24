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
- Živá telemetrie s obnovou stavu každé 2 s (nastavitelné 1–60 s v Možnostech integrace)
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

Pokud nabíječka přestane odpovídat, integrace postupně zpomalí dotazování (až na 30 s), aby se nabíječka mohla zotavit. Po 60 s bez odpovědi se entity označí jako nedostupné, místo aby ukazovaly zamrzlé hodnoty.

Po aktualizaci karty v mobilní aplikaci Home Assistant: pokud se stále načítá stará verze, použijte v aplikaci *Nastavení → Companion app → Ladění → Obnovit frontend cache* (nebo aplikaci restartujte).

Hostname se znovu překládá každých 60 minut. Pokud komunikace se zapamatovanou IP selže kvůli síťové chybě, integrace okamžitě provede nový DNS překlad a požadavek jednou zopakuje.

Chyba autentizace nevyvolává nový DNS překlad.

## EcoVolter karta

Integrace registruje vlastní kartu **EcoVolter**, kterou lze přidat přes běžný editor dashboardu. V editoru karty lze vybrat konkrétní nabíječku, variantu **Minimalistic**, **Compact** nebo **Detailed**, vlastní název, jazyk **Čeština / English** a zobrazení sekce **Plánovač**.

Karta zobrazuje výkon, energii relace, počet aktivních fází a nastavený nabíjecí proud. Umožňuje zapnout/vypnout nabíjení, přepnout 1/3 fáze a nastavit proud 6–16 A. Pro ovládání proudu lze v editoru zvolit slider nebo kompaktní ovládání **− / hodnota / +** s možností ručního zadání. Minimalistic varianta zobrazuje základní údaje přímo ve stavovém řádku, Detailed varianta navíc proud L1–L3, napětí L1–L3 a dlouhodobé statistiky.

## Dashboard příklady

V repozitáři jsou také hotové příklady postavené pouze na nativních kartách Home Assistantu:

- `examples/lovelace/compact.yaml` – kompaktní karta pro běžné ovládání
- `examples/lovelace/detailed.yaml` – detailní karta včetně fází a statistik
- `examples/lovelace/dual-charger.yaml` – přehled pro dvě nabíječky
- `examples/lovelace/scheduler.yaml` – ovládání plánovače nabíjení

Konkrétní ID entit závisí na názvu zařízení vytvořeném v Home Assistantu. V ukázkách proto nahraďte vzorová ID vlastními ID entit.

## Plánovač nabíjení

Plánovač sám zapíná a vypíná nabíjení podle ceny elektřiny. Je součástí integrace, takže běží i bez otevřeného dashboardu a přežije restart Home Assistantu. Po instalaci je v režimu **Ručně**, takže nic nepřepíná, dokud ho nezapnete.

### Krok 1: Nastavení cen (při přidání integrace nebo v Možnostech)

Při přidání integrace se po připojení k nabíječce zobrazí průvodce. Později ho otevřete přes **Nastavení → Zařízení a služby → EcoVolter → ⚙ Konfigurovat**.

**1. Typ ceny**

| Typ | Kdy použít |
|---|---|
| **Spot / senzor ceny** | spotový tarif – cena se čte ze senzoru v HA |
| **Pevný dvoutarif (VT / NT)** | klasický tarif s pevnou cenou; pro jednotarif zadejte stejné ceny do VT i NT |

**2. Ceny**

*Spot / senzor ceny:* vyberte cenový senzor, nebo nechte prázdné pro automatické nalezení. Podporované senzory:

- **Senzor s výslednou cenou (doporučeno):** atribut se seznamem úseků, kde `price` je konečná cena za kWh vč. DPH a distribuce a `tariff` (`VT`/`NT`) je nepovinný. Distribuci nechte 0.

  ```yaml
  prices:
    - start: '2026-10-24T21:00:00+02:00'
      price: 4.7002
      tariff: NT
  ```

- **[Czech Energy Spot Prices](https://github.com/rnovacek/homeassistant_cz_energy_spot_prices):** spotová cena, ke které se přičte distribuce VT/NT.

*Pevný dvoutarif:* cena silové elektřiny VT a NT a distribuce VT a NT, vše za kWh vč. DPH.

**3. Nízký a vysoký tarif (HDO)**

- **HDO senzor:** senzor s okny nízkého tarifu, tedy atributem se seznamem `start`/`end` (např. `next_windows` z integrace ČEZ distribuce), nebo binární senzor (zapnuto = NT). Za koncem známých oken se opakuje vzor posledního dne.
- **Časy VT:** ruční záloha, např. `8:00-9:00, 12:00-13:00, 16:00-17:00, 19:00-20:00`.

Tarif se používá u pevného dvoutarifu, v režimu *Jen NT* a u senzorů bez pole `tariff`.

**4. Auto (nepovinné)**, pro nabíjení do zadaných %:

- **Stav baterie auta:** senzor v % (z integrace auta, např. Škoda, VW, Tesla),
- **Kapacita baterie** v kWh,
- **Účinnost nabíjení:** ztráty, obvykle 85–92 %, výchozí 90 %.

Potřebná energie = (cílová % − aktuální %) × kapacita / účinnost.

**Ceny na další den** se u spotu zveřejňují kolem 14:00, do té doby jsou známé jen do půlnoci. Pokud termín *Hotovo do* leží za koncem známých cen, plánovač neznámou část odhadne (průměr posledních cen). Nyní nabije jen úseky levnější než odhad, zbytek naplánuje po zveřejnění cen. Odhadované úseky jsou v kartě šrafované.

### Krok 2: Zapnutí

V kartě **EcoVolter** je sekce **Plánovač** (u varianty Minimalistic ji zapněte v editoru karty: *Plánovač → Zobrazit*). Zvolte režim:

| Režim | Co dělá | Co nastavit |
|---|---|---|
| **Ručně** | plánovač nic nepřepíná | – |
| **Nejlevnější** | do času *Hotovo do* nabije zadaný počet hodin, kWh nebo auto do zadaných % v nejlevnějších úsecích (i rozptýlených po 15 min) | *Hodiny* / *kWh* / *%*, *Hotovo do*, volitelně *Max. cena* (prázdné = bez limitu) |
| **Pod limit** | nabíjí, kdykoli je cena pod limitem | *Max. cena* |
| **Jen NT** | nabíjí jen v nízkém tarifu | HDO senzor nebo časy VT |

Příklad: chci mít ráno nabito 3 hodiny → **Nejlevnější**, *Hodiny* `3`, *Hotovo do* `07:00`.

*Hotovo do* má i výběr dne: **Dnes** znamená nejbližší výskyt daného času (opakuje se každý den), **Zítra** a **Pozítří** nastaví pevný den. Když je teď 12:00 a chcete nabito zítra v 15:00, zvolte *Zítra* a `15:00`. Po uplynutí pevného termínu se plánovač vrátí k denní variantě. Pod tlačítky se zobrazí plán („Naplánováno 3 h · start 01:15 · odhad 25 Kč“) a časová osa cen, kde jsou vybrané úseky zvýrazněné.

### Jak se chová

- Plán se přepočítává průběžně, také když kolem 14:00 přijdou ceny na zítřek a když se změní cíl nebo termín.
- **Po splnění cíle je plánovač hotový** a sám už nabíjení nespustí: ani po odjetí a novém připojení auta, ani po uplynutí termínu. Nový plán se spustí, až nastavíte cíl, termín nebo režim (stačí i stejná hodnota, např. z denní automatizace), nebo tlačítkem **Nabít znovu** v kartě (entita *Nabít znovu*).
- Když si nabíječka při připojení auta sama povolí nabíjení, plánovač to nebere jako ruční zásah a nabíjení podle plánu hned zase vypne.
- Nabitý čas/energie se počítá od posledního termínu *Hotovo do*.
- Cíl v kWh se přepočítává na čas podle aktuálního výkonu (nebo podle nastaveného proudu a fází), je to odhad.
- Když nabíjení ručně zapnete nebo vypnete (vypínač v HA, aplikace EcoVolter), plánovač to respektuje, dokud plán sám nezmění rozhodnutí. **Jakákoli změna plánu** v kartě nebo v entitách (režim, cíl, termín, max. cena) ale převezme řízení a nabíjení okamžitě přepne.
- U cíle v **%** se průběžně sleduje senzor auta a po dosažení cílových % se nabíjení hned zastaví, i když plán počítal s delší dobou. Bez hodnoty ze senzoru plánovač nenabíjí a karta to ohlásí.
- Pokud do termínu nestačí čas (nebo úseky pod limitem), karta ukáže varování, kolik se stihne.

### Entity plánovače

Všechno lze ovládat i z automatizací a skriptů:

| Entita | Význam |
|---|---|
| `select.…_rezim_nabijeni` / *Režim nabíjení* | `manual`, `cheapest`, `price_limit`, `low_tariff` |
| *Cíl nabíjení* (select) | `hours`, `energy` nebo `soc` |
| *Hodin nabíjení*, *Nabít energie*, *Nabít do* (%), *Maximální cena* (number) | parametry plánu |
| *Hotovo do* (time) | termín |
| *Další plánované nabíjení* (sensor) | čas dalšího startu, v atributech celý plán a odhad ceny |
| *Plánované nabíjení teď* (binary_sensor) | zapnuto, když plán chce právě nabíjet |
| *Cena elektřiny vč. distribuce* (sensor) | aktuální cena za kWh |

Přesná ID entit najdete v **Nastavení → Zařízení a služby → EcoVolter → zařízení**. Hotový příklad dashboardu z nativních karet je v `examples/lovelace/scheduler.yaml`.

Příklad automatizace – každý večer v 18:00 naplánovat 3 h do 6:30:

```yaml
alias: EcoVolter – noční nabíjení
triggers:
  - trigger: time
    at: "18:00:00"
actions:
  - action: number.set_value
    target: { entity_id: number.ecovolter_hodin_nabijeni }
    data: { value: 3 }
  - action: time.set_value
    target: { entity_id: time.ecovolter_hotovo_do }
    data: { time: "06:30:00" }
  - action: select.select_option
    target: { entity_id: select.ecovolter_rezim_nabijeni }
    data: { option: cheapest }
```

## Poznámky

EcoVolter a jeho lokální API jsou produkty/služby třetí strany. Tento projekt je nezávislá integrace pro Home Assistant a není oficiálně spojen s výrobcem.

Automatizace v Home Assistantu nenahrazují elektrické jištění ani jiné bezpečnostní prvky elektroinstalace.

## Licence

MIT © 2026 IT síť s.r.o.
