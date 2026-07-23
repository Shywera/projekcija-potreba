# Nabava - projekcija zaliha i preporuke za nabavu

Web aplikacija za tjednu uskladu zaliha u tiskari samoljepljivih etiketa. Iz PAUK Excel
exporta računa što treba naručiti i crta punu projekciju zalihe kroz vrijeme za svaki
artikl - zamjena za stari desktop PDF alat "Tjedna usklada".

## Zašto

Stari alat je prikazivao samo jedan datum ("pada DD.MM."). To zna lažno alarmirati: artikl
može privremeno pasti u minus u simulaciji, ali ako narudžba stigne prije toga i vrati
zalihu iznad minimuma, ne treba se naručivati. Ova app kombinira trošenje (radni nalozi) I
dolazak robe (narudžbe) u jednu krivulju pa se točno vidi kada i zašto nešto (ni)je hitno.

## Mogućnosti

- **Pretraga po šifri ili nazivu** - traži među SVIM materijalima iz exporta (ne samo praćenim)
  i odmah dobiješ graf/izvještaj za bilo koji; jednim klikom ga možeš dodati u praćene
- **Rekapitulacija za nabavu** - što treba naručiti, grupirano po dobavljaču
- **Povijesni + projekcijski graf** - po artiklu, u jednoj vremenskoj osi: stvarno izmjereno
  stanje iz prošlih uploada (povijest) koje se nastavlja u projekciju unaprijed (trošenje +
  dolazak); "danas" linija, označeni vikendi, linija minimuma
- **Arhiva exporta** - svaki učitani Excel se čuva; stari se mogu pregledati, preuzeti ili
  ponovno prikazati; povijest se koristi za povijesne grafove
- **Pametan status** - razlikuje trajni pad (hitno) od privremenog pada koji se oporavi
  dolaskom narudžbe (nije hitno)
- **Upravljanje šiframa** - koje artikle pratiti, kategorija, minimum, opis (kroz web, umjesto
  ručnog uređivanja Excela)
- **Upozorenja** - stari podaci (export > 24h), šifra koje nema u exportu, odstupanje od ERP-a

## Tehnologije

FastAPI · SQLAlchemy 2.0 · SQLite · Jinja2 · Alpine.js · Tailwind CSS · Chart.js · luxon · pandas

## Brzi start (Windows)

1. Instalirajte [Python 3](https://python.org) (*Add Python to PATH*)
2. Pokrenite **`run.bat`** - prvi put izgradi okruženje (~1-2 min)
3. Otvorite **http://localhost:8602** i učitajte PAUK export (IZVJEŠĆE STANJA MATERIJALA ...)

Za pristup s drugog računala na mreži: **`dev-wifi.bat`** (prikaže mrežni URL).

## Priprema za drugo računalo

Instalirajte Python 3, kopirajte folder (ili `git clone`), dvoklik na `run.bat`. Baza je
lokalna po računalu - svako računalo učitava svoj export. Nema prijave (jednokorisnički alat).

## Povezani projekti

[ERP/MES/WMS](https://github.com/Shywera/erp) · [WMS](https://github.com/Shywera/wms) ·
[Reklamacije](https://github.com/Shywera/reklamacije) · [Ponude](https://github.com/Shywera/Ponude)
