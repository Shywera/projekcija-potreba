# CLAUDE.md

Kontekst za Claude Code. Ovo je jedini kontekst koji putuje između računala kroz git
(Claudova lokalna memorija se NE sinkronizira). Na kraju sesije ažuriraj "Trenutno stanje"
i pokreni `spremi.bat`.

## Što je ovo
Samostalna **Nabava** web-aplikacija za tiskaru samoljepljivih etiketa - zamjena za stari
desktop PDF alat "Tjedna usklada". Iz PAUK Excel exporta (ručni upload) za svaki praćeni
artikl računa treba li se naručiti i crta **punu projekciju zalihe kroz vrijeme** (trošenje
iz radnih naloga + dolazak iz narudžbi), umjesto jednog statičnog "pada <datum>".

Razlog postojanja: stari alat je za artikl koji privremeno padne u minus (npr. boja na 1000kg
padne na -200) prikazivao lažni alarm, iako narudžba stigne prije toga i vrati zalihu iznad
minimuma. Ova app to rješava - status na listi koristi PUNU projekciju (trošenje+dolazak), a
graf pokazuje cijelu krivulju pa kolegica vidi ZAŠTO nešto (ni)je hitno.

FastAPI + SQLAlchemy 2.0 + SQLite + Jinja2 + HTMX + Alpine + Tailwind (CDN) + Chart.js (CDN,
samo na detalj-stranici). Isti skeleton kao WMS-app / Reklamacije-app.

## Pokretanje i alati (Windows, .bat)
- `run.bat` - lokalno, port **8602**; prvi put gradi `.venv` (self-healing: rebuild ako
  `import fastapi,uvicorn,pandas` padne na drugom računalu).
- `dev-wifi.bat` - na `0.0.0.0` + mrežni URL (kolegica na drugom PC-u pristupa preko mreže).
- `backup.bat` - ručni backup baze. `update.bat` - `git pull` + osvježi deps.
  `spremi.bat` - add+commit+pull+push.
- Ručni test: `.venv\Scripts\python.exe` + `pytest tests/` ili FastAPI `TestClient`
  (`httpx` je u venvu lokalno, NIJE u `requirements.txt`).

## Arhitektura (v2)
```
app/main.py                FastAPI: create_all + _migracija() (idempotentni ALTER + v1->v2
                           preslikavanje artikl_stanje->stanje_snapshot), seed, uploads/,
                           /backup, / -> /nabava. BEZ auth-a (svjesno, vidi dolje).
app/core/                  config (pydantic-settings, .env) + database + backup (isto kao braća).
app/modules/nabava/
  models.py                Artikl (konfiguracija), Snapshot (POVIJEST uploada + datoteka/aktivan),
                           StanjeSnapshot (izracunato po snapshotu, AKUMULIRA), Dogadjaj
                           (vremenska linija - samo aktivni snapshot).
  seed.py                  KATEGORIJE_BASE (63 artikla / 13 kat.) + seed u praznu bazu.
  pauk.py                  NISKI NIVO citanja PAUK exporta - doslovan prijenos indeksa
                           stupaca i normalizacije iz desktop alata (0.4). NE prepisivati
                           "slicnim" kodom - tiho puca za dio sifri.
  service.py               PRAVA logika: fali, projekcija_puna (trosenje+dolazak+oporavak),
                           tocke_grafa, stil_statusa (semanticki tip za .badge-*), obradi_upload
                           (dedup + spremi file + AKUMULIRA), povijest_stanja, kombinirana_krivulja.
  routes.py                dashboard(?snapshot) / ucitaj / arhiva(preuzmi/aktiviraj/obrisi) /
                           sifre (CRUD) / artikl/{sifra} (kombinirani graf).
app/templates/nabava/      base (paleta+badge stilovi) + dashboard + ucitaj + arhiva + detalj
                           (Chart.js+luxon) + sifre + sifre_forma.
tests/test_trajektorija.py Scenarij iz razgovora + povijest/kombinirana krivulja + dedup (11 testova).
uploads/                   spremljeni sirovi .xlsx exporti (gitignore) - jedan po snapshotu.
```

## Kako se računa (bitno)
- **fali** = "treba naručiti" = `max(0, min - nak_nar)` - ISTO kao desktop 0.4. `min` je po
  artiklu: broj | POSITIVE (nak_nar > 0) | COMB_3 (zbroj nak_nar SVIH COMB_3 sifri >= 3).
  `nak_nar` (stupac 22) već uračunava pokrivene narudžbe, pa je to autoritet za "treba li".
- **projekcija_puna** (service.py) hoda kroz kombiniranu vremensku liniju: TROSENJE iz radnih
  naloga = `max(0, predvidjeno[46] - zaduzeno[47])` @ rok[42] (zaduzeno-fix je bio glavni bug
  popravljen u 0.4 - već izdani materijal je u stanju, ne oduzimati ga opet), DOLAZAK iz
  narudžbi = kolicina[34] @ rok_isporuke[39]. Vraća status + `oporavlja_li_se` (penje li se
  bilanca natrag >0 nakon pada). **Znacka statusa na dashboardu MORA koristiti ovu punu
  verziju** - ako se "pojednostavi" natrag na trosenje-only, lazni alarm se vraca.
- **stil_statusa** stupnjuje: ISPOD0/KASNI = crveno/naranca; PADA bez oporavka <=7d crveno,
  8-30d blijedo, >30d bez isticanja; **PADA + oporavlja_li_se = mirna plava "privremeni pad".**
- **provjeri_odstupanje**: obrambeni self-check - zavrsna bilanca simulacije vs nak_nar iz
  ERP-a (razlicit put racuna). Tolerancija relativna (2%) + apsolutni pod (5), jer se na
  stvarnim podacima poklapaju do na sitni sum per-row clippanja. Odstupanje -> suptilna ⚠.

## Uvoz cijele mape + aktivni snapshot (v2)
- `service.uvezi_iz_mape(db, mapa)` uveze SVE PAUK exporte iz mape (naziv sadrzi "STANJA
  MATERIJALA", .xlsx) cije datum_exporta jos nije u arhivi (peek_datum cita samo zaglavlje za
  brzu dedup provjeru). Zadana mapa = `~/Downloads` (racunalo koje vrti server). Koristeno za
  jednokratni backfill povijesti (61 export uvezen 2026-07-21). NEMA UI gumba (korisnik nije htio).
- `_postavi_aktivni_najnoviji(db)` - aktivni (dashboard) = snapshot s NAJKASNIJIM datum_exporta,
  ne zadnji uploadan. Zove se u obradi_upload. Tako dodavanje STARIJEG exporta ne pomakne
  dashboard s aktualnog stanja (korisnik pitao "sto ako se doda stara tablica"). Povijesni graf
  ionako sortira po datumu pa se stara tocka slozi kronoloski.

## Kako povijesni graf NE duplicira potrošnju (bitno - korisnik je pitao)
- **Povijesna linija** = apsolutno STANJE (stupac 11) koje PAUK javi po snapshotu - NEOVISNA
  mjerenja, NE zbroj dogadjaja. Isti radni nalog u dva excela ne duplicira nista jer se u
  povijesti uopce ne broji kao dogadjaj, samo se cita "koliko fizicki ima".
- **Projekcija** = dogadjaji AKTIVNOG snapshota. Dogadjaji se drze PO SNAPSHOTU (svaki svoje;
  NE globalni wipe - to je lomilo projekciju kod bulk uvoza jer zadnji obradjeni file != aktivni
  po datumu). Nema akumulacije potrosnje (svaki snapshot je neovisan skup dogadjaja).
- **Dedup**: `obradi_upload` prvo obrise postojeci snapshot s ISTIM datum_exporta (+ file +
  retke) pa upise novi -> re-upload istog excela je idempotentan. Razliciti dani = zasebne
  tocke (svrha povijesti). datum_exporta=None se ne deduplicira (ne zna se je li isti).

## Konvencije i zamke (naučeno)
- **SVJESNA ODSTUPANJA od braće WMS-app/Reklamacije-app (ne slučajno):**
  1. **BEZ auth-a** - oba brata TRAŽE prijavu (Reklamacije ima bcrypt+sesije+audit). Ovdje
     preskočeno: jednokorisnički alat, lokalno na zahtjev, podaci = interne zalihe (ne PII).
     Posljedica: `dev-wifi.bat` izlaže i `/nabava/ucitaj` (briše/prepisuje) na LAN bez zaštite.
     Prihvatljivo za ovaj opseg. Ako ikad zatreba, `auth` modul se kopira iz Reklamacije-app.
  2. **pandas ovisnost** - braća namjerno koriste čist openpyxl. Ovdje se pandas ZADRŽAVA jer
     se prenosi već testirana pandas-bazirana logika iz 0.4 (filter/sort DataFramea). NE
     prepisivati na openpyxl - to bi bio nov, netestiran kod baš gdje najviše treba biti točan.
  3. `CLAUDE.md` OVDJE ide u git (kod braće je greškom u `.gitignore` iako tvrde suprotno).
- **Graf (detalj.html)**: Chart.js + luxon + annotation + **zoom plugin (+ hammerjs)** preko
  CDN-a. NE koristi Chart.js date-adapter (chartjs-adapter-luxon je bio nepouzdan/404) - x-os je
  `type:'linear'` s epoch-ms, luxon SAMO za formatiranje/vikende. Anotacije: "danas" vertikala,
  vikend-trake (rgba plava 0.07 - vidljive tek kad se zumira/fokusira, ne preko mjeseci), min +
  nula. Boje HARDKODIRANE hex (canvas ne cita CSS var).
  **Zoom/pan (bitno)**: pocetni pogled scale.x = FOKUS (zadnje stanje + projekcija) = i "original"
  (pa dvoklik/`resetZoom()` vraca ovamo). `zoom.limits.x` = CIJELI raspon (xMin-pad..xMax+pad) +
  minRange 3 dana -> slobodan scroll/zoom do najstarije povijesti (pan postuje limite, ne
  original). BEZ gumba (korisnik ih nije htio - scroll ionako pokazuje sve); dvoklik = reset.
  NE koristiti setTimeout/zoomScale trikove (raniji pokusaj s gumbima je resetirao zoom).
- **stil_statusa** vraca `{"tip","oznaka"}` (semanticki tip: critical/serious/info/ok/muted),
  stiliziran kao `.badge-<tip>` u base.html (dataviz status paleta). NE vraca vise Tailwind klase.
- **Migracija v1->v2**: idempotentna u `main.py:_migracija()`. Preslikava `artikl_stanje` (v1)
  u `stanje_snapshot` pa dropa staru tablicu; ALTER dodaje snapshot.datoteka/aktivan i
  dogadjaj.snapshot_id. Non-destruktivno (v1 test-snapshot postane 1. povijesna tocka).
- **Route ordering:** detalj je namjerno `/nabava/artikl/{sifra}`, NE goli `/nabava/{sifra}` -
  zaseban prefiks izbjegava klasu buga gdje `/{id}` proguta statičke rute (`/sifre`, `/ucitaj`).
- **Grupiranje po kategoriji ide u Pythonu** (`service.grupiraj_po_kategoriji`), NE Jinja
  `|groupby` (koji abecedno sortira i poremeti radni poredak "BIJELA BOJA" prije "CMYK...").
- **Upload = wipe+reinsert** ArtiklStanje/Dogadjaj unutar JEDNE transakcije (rollback na
  grešci - neuspio upload ne ostavi napola obrisane podatke). Samo zadnji upload se čuva
  (Snapshot je upsert, ne povijest) - po dizajnu.
- **Sifra konfigurirana ali nije u exportu** -> ostaje bez ArtiklStanje reda -> dashboard je
  prikaže kao "nije pronađeno" (za razliku od desktop alata koji ju je tiho preskakao).
- **.bat MORA biti CRLF + čisti ASCII** (Write daje LF -> cmd se instant-zatvori; Croatian
  dijakritika isto puca). Konverzija: `awk '{sub(/\r$/,""); printf "%s\r\n",$0}'`; provjera
  `od -c` ili Python `raw.count(b'\r\n')`. Zagrade u `echo` koristiti samo u goto-formi.
- **Python 3.14 venv nije prenosiv** -> `run.bat` self-healing (rebuild ako import padne).
- **pandas verzija:** 2.3.3 (2.2.3 se ne builda na Py 3.14 bez Visual Studio bild alata).
- **Portovi:** ERP=8000, WMS-app=8600, Reklamacije-app=8601, **Nabava-app=8602**.
- **NIKAD ne commitati:** `.env`, `*.db`, `.venv`, `backup/`, `__pycache__`.

## PAUK export - indeksi stupaca (0-based, u pauk.py)
sifra=0, naziv=1, dobavljac=2, skladiste=3 (SKLADIŠTE MATERIJALA=stanje / U tijeku,Plan=nalozi
/ Narudžba=dolazak), stanje=11, nak_rn=17, nak_nar=22, rok_RN=42, br_RN=43, predvidjeno=46,
zaduzeno=47, kol_narudzba=34, rok_narudzba=39 (RAZLIČIT od rok_RN!), br_narudzbe=37.
Datum exporta je tekst zaglavlja stupca 1 (npr. "22.04.2026. 08:26").

## Trenutno stanje (ažuriraj na kraju sesije)
- 2026-07-21 (v1): prenesena i validirana logika iz "Tjedna usklada 0.4" - brojevi se
  poklapaju s 0.4 PDF-om; artikl 50102010100037 (u 0.4 "PADA 06.08") ispravno OK jer se vide
  2 isporuke +5000.
- 2026-07-21 (v2): DODANO - moderni UI (dataviz paleta, badge s tockicom, stat-trake, kartice),
  ARHIVA uploada (Snapshot=povijest, sirovi .xlsx u uploads/, preuzmi/aktiviraj/obrisi), POVIJESNI
  GRAF (kombinirana krivulja: stvarna izmjerena povijest + projekcija u jednoj vremenskoj osi,
  "danas" linija, vikend-trake). Dedup istog exporta. 11 pytest testova. Vizualno provjereno u
  Chromiumu (dashboard/arhiva/2 grafa). nabava.db ima 5 stvarnih exporta (20/21/22.04 + 20/21.07).
  Migracija v1->v2 testirana non-destruktivno.
- GitHub repo: **`Shywera/projekcija-potreba`** (vlastiti git repo, NE dio home repoa; uploads/
  + *.db gitignore). Bulk uvoz: 61 stvarni PAUK export iz Downloadsa (prosinac 2025 - srpanj 2026)
  -> bogat povijesni graf. Dogadjaji po-snapshotu (fix), zoom bez gumba (dvoklik reset).
- Sljedeće / ideje: PDF/Excel izvoz ako zatreba, filter "samo za naručiti", trend agregat na
  dashboardu. Namjerno odgođeno.
