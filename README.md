# EcoVolter pro Home Assistant

**Čeština** | [English](README.en.md)

Integrace pro nabíječky elektromobilů **EcoVolter** do Home Assistantu. Komunikuje **lokálně** přes Local API nabíječky, bez cloudu. Obsahuje vlastní kartu pro dashboard a **plánovač nabíjení podle ceny elektřiny**: spot i pevné tarify, HDO a až 3 auta.

> **Verze 1.0.0** – první veřejná verze k testování. Budeme rádi za zpětnou vazbu v [Issues](https://github.com/itsit-cz/HA-ecovolter/issues).

---

## Obsah

1. [Funkce](#funkce)
2. [Požadavky](#požadavky)
3. [Instalace](#instalace)
4. [Přidání nabíječky – průvodce](#přidání-nabíječky--průvodce)
5. [Karta EcoVolter](#karta-ecovolter)
6. [Plánovač nabíjení](#plánovač-nabíjení)
7. [Auta](#auta)
8. [Entity](#entity)
9. [Příklady automatizací](#příklady-automatizací)
10. [Formáty cenových a HDO senzorů](#formáty-cenových-a-hdo-senzorů)
11. [Řešení problémů](#řešení-problémů)
12. [Omezení a známé problémy](#omezení-a-známé-problémy)
13. [Vývoj a testy](#vývoj-a-testy)

---

## Funkce

**Nabíječka**

- Lokální komunikace přes Local API (HMAC), bez cloudu
- Více nabíječek v jednom Home Assistantu
- Připojení přes sériové číslo, IP adresu nebo hostname
- Stav vozidla a nabíjení, výkon, energie relace, celkem nabito, počet a doba nabíjení
- Proud a napětí jednotlivých fází, počet aktivních fází
- Povolení a zakázání nabíjení, přepínání 1f/3f, nabíjecí proud 6–16 A
- Stabilní komunikace: nové spojení pro každý požadavek, postupné zpomalení dotazování při výpadku, po 60 s bez odpovědi stav *nedostupné* místo zamrzlých hodnot

**Plánovač nabíjení**

- Režimy **Ručně · Nejlevnější · Pod limit · Jen NT**
- Cíl v **hodinách**, **kWh** nebo **% baterie auta**
- Termín **Hotovo do** s výběrem dne (dnes / zítra / pozítří)
- Nejlevnější úseky, i rozptýlené po 15 minutách; volitelná maximální cena
- Ceny: **spot** (senzor s výslednou cenou, nebo spot + přirážka + distribuce + DPH), **pevný dvoutarif**, **pevný jednotarif**
- Nízký a vysoký tarif: **ČEZ Distribuce** (rozvrh HDO na 7 dní), jiný HDO senzor, nebo ručně zadané časy
- Spot: počítá s tím, že ceny na další den se zveřejňují kolem 14:00
- Po splnění cíle už sám nenabíjí, ani po odpojení a novém připojení auta
- Ruční zásah má přednost, změna plánu převezme řízení okamžitě

**Auta**

- Až 3 auta na nabíječku: senzor baterie, kapacita, účinnost, senzor připojení
- Automatické rozpoznání připojeného auta, cílová % pro každé auto zvlášť

**Karta**

- Varianty Minimalistic / Compact / Detailed, čeština a angličtina
- Přepínač aut, sekce plánovače s časovou osou cen a odhadem ceny nabití
- Funguje na mobilu i pro uživatele bez admin práv

---

## Požadavky

- **Home Assistant 2025.3 nebo novější** (testováno na 2026.2)
- Nabíječka **EcoVolter** se zapnutým **Local API** a jeho **tajným klíčem**
- Nabíječka a Home Assistant ve stejné síti

Pro plánovač podle ceny navíc podle tarifu:

- **spot:** senzor ceny, například integrace [Czech Energy Spot Prices](https://github.com/rnovacek/homeassistant_cz_energy_spot_prices) nebo vlastní senzor s výslednou cenou,
- **HDO od ČEZ:** integrace ČEZ HDO, ze které se použije senzor *Surová data* (nepovinné),
- **cíl v %:** integrace vašeho auta se senzorem stavu baterie (nepovinné).

---

## Instalace

### HACS (doporučeno)

1. **HACS → tři tečky → Vlastní repozitáře** (Custom repositories)
2. Repozitář `https://github.com/itsit-cz/HA-ecovolter`, typ **Integrace**
3. Vyhledejte **EcoVolter** a klikněte na **Stáhnout**
4. **Restartujte Home Assistant**

### Ručně

Zkopírujte složku `custom_components/ecovolter` do `/config/custom_components/ecovolter` a restartujte Home Assistant.

### Po každé aktualizaci

Restartujte Home Assistant a **obnovte stránku v prohlížeči** (Ctrl+Shift+R). V mobilní aplikaci použijte *Nastavení → Companion app → Ladění → Obnovit frontend cache*. Jinak může zůstat načtená stará verze karty.

---

## Přidání nabíječky – průvodce

**Nastavení → Zařízení a služby → Přidat integraci → EcoVolter**

```
1. Připojení: sériové číslo / IP / hostname + tajný klíč Local API
2. Jaký máte tarif?
   ├─ Spot ── Máte senzor s výslednou cenou (vč. distribuce a DPH)?
   │          ├─ Ano → vyberte senzor
   │          │        └─ obsahuje i tarif VT/NT? → krok 3 se přeskočí
   │          └─ Ne  → senzor spotu + přirážka + distribuce VT/NT + DPH
   ├─ Pevný dvoutarif → silová elektřina VT/NT + distribuce VT/NT + DPH
   └─ Pevný jednotarif → silová elektřina + distribuce + DPH (bez kroku 3)
3. Odkud brát nízký a vysoký tarif? ČEZ Distribuce · jiný HDO senzor · ručně
4. Auta: 0–3
5. Souhrn: ceny s DPH, dnešní časy NT, auta → Uložit
```

- **Ceny se zadávají bez DPH.** Výsledná cena = (spot nebo silová elektřina + přirážka + distribuce) × (1 + DPH). U senzoru s výslednou cenou se nic nepřičítá.
- Průvodce kontroluje vybrané senzory. Když senzor nemá ceny nebo rozvrh ve správném formátu, ozve se hned.
- **Tajný klíč Local API nikdy nezveřejňujte.** Ukládá se jen do konfigurace Home Assistantu.

### Změna nastavení

**Nastavení → Zařízení a služby → EcoVolter → ⚙ Konfigurovat** otevře menu:

| Položka | Co upravuje |
|---|---|
| Ceny a tarif | typ tarifu a ceny (stejné větvení jako v průvodci) |
| Nízký a vysoký tarif (VT/NT) | zdroj VT/NT |
| Auta | počet aut a jejich nastavení |
| Interval obnovy | jak často se čte stav nabíječky (1–60 s, doporučeno 2 s) |

Nastavení z verzí 0.x se při aktualizaci převede automaticky.

---

## Karta EcoVolter

Integrace přidává vlastní kartu. **Upravit dashboard → Přidat kartu → EcoVolter.**

Nastavení v editoru karty:

| Volba | Popis |
|---|---|
| Nabíječka | která nabíječka EcoVolter |
| Varianta | **Minimalistic** (stav v jednom řádku) · **Compact** · **Detailed** (navíc fáze L1–L3 a statistiky) |
| Ovládání proudu | slider, nebo − / hodnota / + |
| Plánovač | Automaticky (skrytý u Minimalistic) · Zobrazit · Skrýt |
| Jazyk | Čeština / English |
| Název | prázdné = název zařízení z integrace |

**Co karta obsahuje**

- přehled: výkon, energie relace, aktivní fáze, nastavený proud,
- **přepínač aut** se stavem baterie. Když integrace nepozná, které auto je připojené, zeptá se: *„Které auto je připojené?“*,
- tlačítka **Nabíjení** a **3 fáze**, nastavení proudu,
- **Plánovač:** režimy, cíl (Hodiny / kWh / %), Hotovo do (den + čas), maximální cena, stav plánu a **časová osa cen**. Zvýrazněné jsou naplánované úseky, šrafované odhadované ceny a červeně podtržený VT. Ťuknutím na sloupec uvidíte čas a cenu.

Příklady dashboardů z nativních karet Home Assistantu jsou ve složce [`examples/`](examples/).

---

## Plánovač nabíjení

Plánovač běží v integraci, takže funguje i bez otevřeného dashboardu a přežije restart. Po instalaci je v režimu **Ručně** a nic nepřepíná.

### Režimy

| Režim | Co dělá |
|---|---|
| **Ručně** | plánovač nic nepřepíná |
| **Nejlevnější** | do termínu *Hotovo do* nabije zadaný cíl v nejlevnějších úsecích; volitelná *Max. cena* zakáže dražší úseky |
| **Pod limit** | nabíjí, kdykoli je cena pod *Max. cenou* |
| **Jen NT** | nabíjí jen v nízkém tarifu (u jednotarifu skryto) |

### Cíl (režim Nejlevnější)

- **Hodiny:** doba nabíjení,
- **kWh:** energie; přepočítává se na čas podle aktuálního výkonu nebo nastaveného proudu a fází,
- **%:** auto do zadaných % baterie (jen u auta se senzorem baterie a kapacitou). Potřebná energie = (cíl − aktuální %) × kapacita / účinnost. Po dosažení cílových % se nabíjení **hned zastaví**.

### Hotovo do

- **Dnes:** nejbližší výskyt času (opakuje se denně). Když je 12:00 a zvolíte 07:00, myslí se zítřek ráno.
- **Zítra / Pozítří:** pevné datum, o půlnoci se neposune. Po uplynutí se vrátí na denní variantu.

### Jak se plánovač chová

- **Ceny na další den** se u spotu zveřejňují kolem 14:00. Pokud termín leží za koncem známých cen, plánovač neznámou část odhadne (průměr posledních cen). Nyní nabije jen úseky levnější než odhad a zbytek naplánuje po zveřejnění cen.
- **Po splnění cíle** je hotovo: nabíjení se samo nespustí ani po odpojení a novém připojení auta, ani po termínu. Nový plán spustí tlačítko **Nabít znovu**, změna cíle, termínu nebo režimu, případně nastavení stejné hodnoty z automatizace.
- **Ruční zásah** (tlačítko Nabíjení, aplikace EcoVolter) má přednost, dokud plán sám nezmění rozhodnutí.
- **Změna plánu** v kartě nebo přes entity převezme řízení a nabíječku přepne **okamžitě**.
- **Připojení auta:** stav nabíječky se načte hned. Když si nabíječka sama povolí nabíjení, plánovač to nebere jako ruční zásah.
- Pokud do termínu nestačí čas, karta ukáže varování, kolik se stihne.

---

## Auta

V průvodci (nebo *Konfigurovat → Auta*) lze zadat **až 3 auta**:

| Pole | Popis |
|---|---|
| Název | jedinečný název, zobrazí se v kartě |
| Senzor baterie (%) | z integrace auta; umožní cíl v % |
| Kapacita baterie (kWh) | **využitelná** kapacita, povinná se senzorem baterie |
| Účinnost nabíjení (%) | ztráty při nabíjení, výchozí 90 % (obvykle 85–92 %) |
| Senzor připojení | „kabel připojen“, „nabíjí se“ nebo stav nabíjení z integrace auta; umožní rozpoznání |

**Automatické rozpoznání:** po připojení k nabíječce se integrace až 2 minuty dívá na senzory připojení aut. Když hlásí připojeno právě jedno auto, vybere ho. Jinak se karta zeptá. Ruční výběr v kartě má přednost. Za „připojeno“ se považují stavy jako `on`, `connected`, `plugged`, `charging`.

- **Cílová %** si pamatuje každé auto zvlášť.
- **Jiné auto:** návštěva nebo auto bez senzoru, cíl jen v hodinách nebo kWh.
- Když se připojí jiné auto než to, které má splněný cíl, začne se nový plán.

---

## Entity

Názvy jsou podle jazyka Home Assistantu. ID entit závisí na názvu zařízení.

**Nabíječka**

| Entita | Typ | Popis |
|---|---|---|
| Vozidlo připojeno | binary_sensor | |
| Nabíjení | binary_sensor | nabíjí se právě teď |
| Aktuální výkon | sensor (kW) | |
| Aktuální relace | sensor (kWh) | energie aktuální relace |
| Celkem nabito | sensor (kWh) | celoživotní počítadlo, pro statistiky a Energie |
| Počet nabíjení, Celková doba nabíjení | sensor | statistiky |
| Proud L1–L3, Napětí L1–L3 | sensor | |
| Aktivní fáze | sensor | počet fází nad 1 A |
| Nastavený proud | sensor (A) | proud nastavený v nabíječce |
| Povolit nabíjení | switch | |
| 3f nabíjení | switch | |
| Nabíjecí proud | number (6–16 A) | |

**Plánovač**

| Entita | Typ | Hodnoty |
|---|---|---|
| Režim nabíjení | select | `manual`, `cheapest`, `price_limit`, `low_tariff` |
| Cíl nabíjení | select | `hours`, `energy`, `soc` |
| Hodin nabíjení | number (h) | |
| Nabít energie | number (kWh) | |
| Nabít do | number (%) | pro vybrané auto |
| Maximální cena | number (Kč/kWh) | 0 = bez limitu |
| Hotovo do | time | |
| Den dokončení | select | `today`, `tomorrow`, `day_after` |
| Auto | select | názvy aut + `other` (jen pokud jsou zadaná auta) |
| Nabít znovu | button | nový plán po splnění cíle |
| Další plánované nabíjení | sensor (čas) | v atributech celý plán, odhad ceny, stav auta |
| Plánované nabíjení teď | binary_sensor | atribut `reason` |
| Cena elektřiny vč. distribuce | sensor (Kč/kWh) | aktuální cena s DPH |

---

## Příklady automatizací

**Každý večer naplánovat nabití do 80 % na 6:30**

```yaml
alias: EcoVolter – noční nabíjení
triggers:
  - trigger: time
    at: "18:00:00"
actions:
  - action: select.select_option
    target: { entity_id: select.ecovolter_cil_nabijeni }
    data: { option: soc }
  - action: number.set_value
    target: { entity_id: number.ecovolter_nabit_do }
    data: { value: 80 }
  - action: time.set_value
    target: { entity_id: time.ecovolter_hotovo_do }
    data: { time: "06:30:00" }
  - action: select.select_option
    target: { entity_id: select.ecovolter_rezim_nabijeni }
    data: { option: cheapest }
```

Nastavení stejné hodnoty spustí nový plán i po splnění předchozího, takže automatizace funguje jako denní rutina.

**Upozornění, když se nestihne nabít**

```yaml
alias: EcoVolter – nestihne se
triggers:
  - trigger: template
    value_template: >
      {{ state_attr('sensor.ecovolter_dalsi_planovane_nabijeni', 'complete') == false
         and states('select.ecovolter_rezim_nabijeni') == 'cheapest' }}
actions:
  - action: notify.notify
    data:
      message: "Auto se do termínu nestihne nabít podle plánu."
```

ID entit (`select.ecovolter_…`) nahraďte svými.

---

## Formáty cenových a HDO senzorů

**Senzor s výslednou cenou:** atribut se seznamem úseků. `price` je konečná cena za kWh, `tariff` je nepovinný a `spot` se použije, když zvolíte „nemám výslednou cenu“.

```yaml
prices:
  - start: '2026-10-24T21:00:00+02:00'
    price: 4.7002
    spot: 3.478
    tariff: NT
```

**Czech Energy Spot Prices:** atributy `čas → cena`. Hodinové i 15minutové ceny, jednotky Kč/kWh nebo Kč/MWh se rozpoznají samy.

**ČEZ HDO – Surová data:** atribut `raw_json` s položkami `datum` (`24.10.2026`) a `casy` (`00:00-08:00; 09:00-12:00; …`). `casy` jsou okna **nízkého tarifu**.

**Jiný HDO senzor:** binární senzor (zapnuto = NT), nebo atribut se seznamem `{start, end}` oken NT.

**Ruční časy VT:** `8:00-9:00, 12:00-13:00, 16:00-17:00, 19:00-20:00`. Okna přes půlnoc jsou povolena (`22:00-02:00`).

---

## Řešení problémů

| Problém | Řešení |
|---|---|
| *Custom element doesn't exist: ecovolter-card* | obnovte stránku (Ctrl+Shift+R), v aplikaci *Obnovit frontend cache* |
| Entity jsou *nedostupné* | nabíječka 60 s neodpovídá: zkontrolujte síť a IP. Integrace se zotaví sama. |
| Hodnoty se aktualizují pomalu | při výpadcích se dotazování zpomalí až na 30 s; po obnovení se vrátí |
| Plánovač nenabíjí | podívejte se do stavu plánu v kartě, případně na atribut `reason` entity *Plánované nabíjení teď* (`manual`, `waiting`, `no_prices`, `no_soc`, `target_reached` …) |
| Cíl v % nejde zvolit | vybrané auto nemá senzor baterie nebo kapacitu |
| Auto se nerozpozná | u auta nastavte senzor připojení; zkontrolujte, jaký stav hlásí (`on`, `connected`, `charging` …) |

**Podrobný log:** do `configuration.yaml` přidejte

```yaml
logger:
  logs:
    custom_components.ecovolter: debug
```

---

## Omezení a známé problémy

- Testováno s nabíječkou EcoVolter II, spotovými cenami a ČEZ Distribuce. Jiné distributory (EG.D, PRE) zatím podporujeme přes obecný HDO senzor nebo ruční časy.
- Cíl v kWh se přepočítává na čas podle výkonu, jde tedy o odhad.
- Kapacita baterie a účinnost jsou na vás. Pro přesnější % dolaďte účinnost.
- Rozpoznání auta závisí na tom, co nabízí integrace auta.
- Automatizace v Home Assistantu nenahrazují jištění ani jiné bezpečnostní prvky elektroinstalace.

---

## Vývoj a testy

```bash
pip install pytest-homeassistant-custom-component
pytest tests
```

Chyby a nápady hlaste v [Issues](https://github.com/itsit-cz/HA-ecovolter/issues). Přehled změn je v [CHANGELOG.md](CHANGELOG.md).

EcoVolter a jeho Local API jsou produkty třetí strany. Tento projekt je nezávislá integrace a není oficiálně spojen s výrobcem.

## Licence

MIT © 2026 IT síť s.r.o.
