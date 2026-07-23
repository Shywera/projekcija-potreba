"""Prava logika: fali/suma_krpe (prijenos iz 0.4), PUNA projekcija (novo - trosenje +
dolazak kombinirano, s detekcijom oporavka), tocke za graf, i orkestracija uploada.
v2: povijest snapshota (arhiva) + kombinirana krivulja (stvarna povijest + projekcija)."""
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.modules.nabava import pauk
from app.modules.nabava.pauk import f
from app.modules.nabava.models import Artikl, Dogadjaj, Snapshot, StanjeSnapshot


def uploads_dir() -> Path:
    """Dir za spremljene sirove .xlsx exporte (uz bazu, u korijenu projekta). Kreira ga."""
    d = Path("uploads")
    d.mkdir(exist_ok=True)
    return d


def zadana_mapa() -> Path:
    """Zadana mapa za uvoz svih exporta odjednom - Downloads racunala koje vrti server."""
    return Path.home() / "Downloads"


def _sigurno_ime(naziv: str) -> str:
    """Ocisti naziv datoteke za spremanje na disk (bez putanja/opasnih znakova)."""
    naziv = os.path.basename(naziv or "export.xlsx")
    naziv = re.sub(r"[^A-Za-z0-9._-]+", "_", naziv).strip("_")
    return naziv or "export.xlsx"


def izracunaj_fali(min_tip: str, min_broj: float | None, nak_nar: float, suma_krpe: float) -> float:
    """Grana-po-grana prijenos iz 0.4 desktop skripte."""
    if min_tip == "COMB_3":
        return max(0.0, 3.0 - suma_krpe)
    if min_tip == "POSITIVE":
        # 0.01 je zastavica "treba naruciti" (za prikaz), ne stvarna kolicina.
        return 0.01 if nak_nar <= 0 else 0.0
    return max(0.0, (min_broj or 0.0) - nak_nar)


def izracunaj_suma_krpe(artikli: list[Artikl], nak_nar_po_sifri: dict[str, float]) -> float:
    """Dinamicki zbroj nak_nar svih trenutno COMB_3-oznacenih sifri (npr. krpe za pranje) -
    ne fiksne dvije sifre kao u prvotnoj desktop verziji (taj bug je vec ispravljen u 0.4)."""
    return sum(nak_nar_po_sifri.get(a.sifra, 0.0) for a in artikli if a.min_tip == "COMB_3")


def dogadjaji_po_sifri(df_nal: pd.DataFrame, df_nar: pd.DataFrame) -> dict[str, list[dict]]:
    """SVI dogadjaji odjednom, grupirani po sifri - jedan prolaz kroz podatke.

    Zamjena za pozivanje dogadjaji_za_sifru() po svakoj sifri: to filtrira cijeli DataFrame
    za svaku sifru posebno, sto je bilo podnosljivo za 52 pracena artikla, ali za SVE
    materijale (~1300) znaci 1300 punih prolaza po exportu -> uvoz bi trajao desecima minuta.
    """
    rez: dict[str, list[dict]] = {}

    if not df_nal.empty:                                    # TROSENJE (radni nalozi)
        datumi = pd.to_datetime(df_nal.iloc[:, pauk.C_ROK], errors="coerce")
        preostalo = (pd.to_numeric(df_nal.iloc[:, pauk.C_KOL], errors="coerce").fillna(0)
                     - pd.to_numeric(df_nal.iloc[:, pauk.C_ZADUZ], errors="coerce").fillna(0)).clip(lower=0)
        for s, d, k, izv in zip(df_nal.iloc[:, pauk.C_SIFRA], datumi, preostalo,
                                df_nal.iloc[:, pauk.C_RN]):
            if pd.isna(d) or k <= 0:
                continue
            rez.setdefault(str(s), []).append(
                {"datum": d, "kolicina": -float(k), "tip": "TROSENJE",
                 "izvor": str(izv) if pd.notna(izv) else None})

    if not df_nar.empty:                                    # DOLAZAK (narudzbe)
        datumi = pd.to_datetime(df_nar.iloc[:, pauk.C_ROK_NARUDZBA], errors="coerce")
        kolicine = pd.to_numeric(df_nar.iloc[:, pauk.C_KOL_NARUDZBA], errors="coerce").fillna(0)
        for s, d, k, izv in zip(df_nar.iloc[:, pauk.C_SIFRA], datumi, kolicine,
                                df_nar.iloc[:, pauk.C_BR_NARUDZBE]):
            if pd.isna(d) or k <= 0:
                continue
            rez.setdefault(str(s), []).append(
                {"datum": d, "kolicina": float(k), "tip": "DOLAZAK",
                 "izvor": str(izv) if pd.notna(izv) else None})

    for lista in rez.values():
        lista.sort(key=lambda x: x["datum"])
    return rez


def dogadjaji_za_sifru(sifra: str, df_nal: pd.DataFrame, df_nar: pd.DataFrame) -> list[dict]:
    """Kombinirana vremenska linija za jednu sifru: TROSENJE (radni nalozi, preostalo =
    max(0, predvidjeno - zaduzeno) - isti fix kao 0.4) + DOLAZAK (narudzbe). Sortirano
    po datumu. Svaka stavka: {datum: pd.Timestamp, kolicina: float, tip: str, izvor: str|None}."""
    dogadjaji: list[dict] = []

    nal = df_nal[df_nal.iloc[:, pauk.C_SIFRA] == sifra].copy()
    if not nal.empty:
        nal["_d"] = pd.to_datetime(nal.iloc[:, pauk.C_ROK], errors="coerce")
        preostalo = (pd.to_numeric(nal.iloc[:, pauk.C_KOL], errors="coerce").fillna(0)
                     - pd.to_numeric(nal.iloc[:, pauk.C_ZADUZ], errors="coerce").fillna(0)).clip(lower=0)
        nal["_k"] = preostalo
        nal = nal.dropna(subset=["_d"])
        for _, r in nal.iterrows():
            if r["_k"] <= 0:
                continue
            izvor = r.iloc[pauk.C_RN]
            dogadjaji.append({"datum": r["_d"], "kolicina": -float(r["_k"]), "tip": "TROSENJE",
                              "izvor": str(izvor) if pd.notna(izvor) else None})

    nar = df_nar[df_nar.iloc[:, pauk.C_SIFRA] == sifra].copy()
    if not nar.empty:
        nar["_d"] = pd.to_datetime(nar.iloc[:, pauk.C_ROK_NARUDZBA], errors="coerce")
        nar["_k"] = pd.to_numeric(nar.iloc[:, pauk.C_KOL_NARUDZBA], errors="coerce").fillna(0)
        nar = nar.dropna(subset=["_d"])
        for _, r in nar.iterrows():
            if r["_k"] <= 0:
                continue
            izvor = r.iloc[pauk.C_BR_NARUDZBE]
            dogadjaji.append({"datum": r["_d"], "kolicina": float(r["_k"]), "tip": "DOLAZAK",
                              "izvor": str(izvor) if pd.notna(izvor) else None})

    dogadjaji.sort(key=lambda d: d["datum"])
    return dogadjaji


def projekcija_puna(stanje: float, dogadjaji: list[dict], danas: pd.Timestamp) -> dict:
    """Hoda kroz PUNU kombiniranu vremensku liniju (trosenje + dolazak) - za razliku od
    stare desktop projekcija() koja gleda samo trosenje. Ovo mora biti izvor znacke
    statusa na dashboardu, ne samo grafa - inace primjer "pada na -200 ali narudzba
    stize prije toga" i dalje pokazuje crvenu znacku na listi.

    Vraca dict: status ('-'|'ISPOD0'|'KASNI'|'PADA'), datum/dani prvog pada <=0,
    oporavlja_li_se (penje li se bilanca >0 nakon tog pada) + datum_oporavka.
    Ako bilanca padne pa se oporavi pa opet padne, prati se samo PRVI ciklus pad/oporavak
    - dovoljno za odluku "treba li paziti na ovo sad", graf ionako pokazuje cijelu krivulju.
    """
    prazno = {"status": "-", "datum": None, "dani": None,
              "oporavlja_li_se": False, "datum_oporavka": None}
    if not dogadjaji:
        if stanje <= 0:
            return {**prazno, "status": "ISPOD0"}
        return prazno

    dogadjaji = sorted(dogadjaji, key=lambda d: d["datum"])

    if stanje <= 0:
        buduci = [d for d in dogadjaji if d["datum"] >= danas]
        if not buduci:
            return {**prazno, "status": "ISPOD0"}
        prvi = buduci[0]
        s = stanje
        oporavak = None
        for d in buduci:
            s += d["kolicina"]
            if s > 0:
                oporavak = d["datum"]
                break
        return {"status": "ISPOD0", "datum": prvi["datum"], "dani": (prvi["datum"] - danas).days,
                "oporavlja_li_se": oporavak is not None, "datum_oporavka": oporavak}

    s = stanje
    pao_na = None
    for d in dogadjaji:
        s += d["kolicina"]
        if pao_na is None:
            if s < 0:
                pao_na = d
        elif s > 0:
            datum_pada = pao_na["datum"]
            status = "KASNI" if datum_pada < danas else "PADA"
            return {"status": status, "datum": datum_pada, "dani": (datum_pada - danas).days,
                    "oporavlja_li_se": True, "datum_oporavka": d["datum"]}

    if pao_na is not None:
        datum_pada = pao_na["datum"]
        status = "KASNI" if datum_pada < danas else "PADA"
        return {"status": status, "datum": datum_pada, "dani": (datum_pada - danas).days,
                "oporavlja_li_se": False, "datum_oporavka": None}
    return prazno


def tocke_grafa(stanje: float, dogadjaji: list[dict], danas: pd.Timestamp) -> list[dict]:
    """Tocke za Chart.js: kumulativna bilanca kroz vrijeme od trenutnog stanja na 'danas'.
    Dogadjaji koji vec kasne (datum < danas) se za CRTANJE prikvace na 'danas' - bilanca
    prije toga nije poznata pa se ne izmislja tocka u proslosti. Dogadjaj.datum u bazi
    ostaje stvarni (kasni) datum - treba ga za 'kasni Xd' u tablici ispod grafa."""
    tocke = [{"x": danas.strftime("%Y-%m-%d"), "y": round(stanje, 2)}]
    s = stanje
    for d in sorted(dogadjaji, key=lambda d: d["datum"]):
        s += d["kolicina"]
        x = max(d["datum"], danas)
        tocke.append({"x": x.strftime("%Y-%m-%d"), "y": round(s, 2)})
    return tocke


def stil_statusa(status: str, dani: int | None, oporavlja_li_se: bool) -> dict:
    """Semanticki tip znacke (stiliziran kao .badge-<tip> u base.html, dataviz status paleta)
    + kratka oznaka. PADA bez oporavka je stupnjevano po hitnosti (>30 dana = bez alarma -
    inace lazno alarmira za nesto sto je daleko). 'tip' je i za sortiranje/filtriranje."""
    if status == "ISPOD0":
        return {"tip": "critical", "oznaka": "ispod 0"}
    if status == "KASNI":
        return {"tip": "critical", "oznaka": f"kasni {abs(dani)}d"}
    if status == "PADA":
        if oporavlja_li_se:
            return {"tip": "info", "oznaka": f"privremeni pad ({dani}d), oporavak"}
        if dani is not None and dani <= 7:
            return {"tip": "critical", "oznaka": f"pada za {dani}d"}
        if dani is not None and dani <= 30:
            return {"tip": "serious", "oznaka": f"pada za {dani}d"}
        return {"tip": "muted", "oznaka": f"pada za {dani}d"}
    return {"tip": "ok", "oznaka": "OK"}


# rangiranje hitnosti - za sortiranje "najhitnije gore" na dashboardu
HITNOST = {"critical": 0, "serious": 1, "info": 2, "muted": 3, "ok": 4}


def provjeri_odstupanje(zavrsna_bilanca: float, nak_nar: float,
                        apsolutni: float = 5.0, relativni: float = 0.02) -> bool:
    """Obrambena provjera: ovo je posve nova, netestirana logika (za razliku od trosenja
    koje je vec provjereno u 0.4) - usporeduje zavrsnu bilancu simulacije s nak_nar iz
    PAUK exporta (koji Pauk sam racuna drugim putem; ta dva puta se na stvarnim podacima
    poklapaju do na sitni sum od per-row clippanja preostalog trosenja). Tolerancija je
    relativna (2%) + apsolutni pod (5) - na kutijama u tisucama par jedinica razlike NIJE
    greska, ali gruba greska (stotine) se i dalje uhvati. Odstupanje -> suptilna napomena."""
    dopusteno = max(apsolutni, relativni * abs(nak_nar))
    return abs(zavrsna_bilanca - nak_nar) > dopusteno


def grupiraj_po_kategoriji(stavke: list) -> list[tuple[str, list]]:
    """Grupira U PYTHONU, ne Jinja |groupby (koji abecedno sortira kljuceve i tiho bi
    poremetio radni poredak kategorija poput 'BIJELA BOJA' prije 'CMYK...'). Ocekuje
    stavke vec sortirane po redoslijedu (vidi upit u routes.py). Prima ili Artikl objekte
    (atribut .kategorija) ili dictove (kljuc "kategorija") - dashboard prosljedjuje
    kombinirane dictove (artikl+stanje+stil), sifre.html sirove Artikl objekte."""
    grupe: dict[str, list] = {}
    poredak: list[str] = []
    for stavka in stavke:
        kat = stavka["kategorija"] if isinstance(stavka, dict) else stavka.kategorija
        if kat not in grupe:
            grupe[kat] = []
            poredak.append(kat)
        grupe[kat].append(stavka)
    return [(kat, grupe[kat]) for kat in poredak]


def obradi_upload(db: Session, filename: str, data: bytes) -> Snapshot:
    """Orkestrira cijeli upload (v2 - AKUMULIRA povijest):
      1) spremi sirovi .xlsx na disk (uploads/)
      2) kreiraj NOVI Snapshot (aktivan=True), postojecima aktivan=False
      3) izracunaj StanjeSnapshot retke za novi snapshot (ne brise stare - povijest)
      4) Dogadjaj: wipe SVE + reinsert za novi (aktivni) snapshot
    Sve u JEDNOJ transakciji; rollback na iznimci + brisanje spremljenog filea (neuspio
    upload ne ostavi ni pola-baze ni siroti file)."""
    df = pauk.ucitaj_i_normaliziraj(data)  # baci gresku ODMAH ako nije PAUK export (prije ikakvih izmjena)
    datum_exporta = pauk.izvuci_datum_exporta(df)
    danas = (pd.Timestamp(datum_exporta.date()) if datum_exporta
             else pd.Timestamp(datetime.now().date()))

    sklad = pauk.sklad_po_sifri(df)
    df_nal = pauk.df_nalozi(df)
    df_nar = pauk.df_narudzbe(df)

    artikli = list(db.scalars(select(Artikl).order_by(Artikl.redoslijed)).all())
    artikl_po_sifri = {a.sifra: a for a in artikli}
    nak_nar_po_sifri = {
        a.sifra: f(sklad[a.sifra].iloc[pauk.C_NAK_NAR])
        for a in artikli if a.sifra in sklad
    }
    suma_krpe = izracunaj_suma_krpe(artikli, nak_nar_po_sifri)
    svi_dogadjaji = dogadjaji_po_sifri(df_nal, df_nar)   # jedan prolaz za sve sifre

    spremljeni_file: Path | None = None
    try:
        # 0) dedup: ako isti export (isti datum_exporta) vec postoji u arhivi, zamijeni ga
        #    (re-upload istog excela je idempotentan - povijesni graf ne dobiva duplu tocku).
        #    Razliciti dani ostaju kao zasebni snapshoti (to je i svrha povijesti). Ako
        #    datum nije citljiv (None), ne dedupliciramo (ne znamo sigurno je li isti).
        if datum_exporta is not None:
            for stari in db.scalars(select(Snapshot).where(Snapshot.datum_exporta == datum_exporta)).all():
                if stari.datoteka:
                    try:
                        Path(stari.datoteka).unlink()
                    except OSError:
                        pass
                db.query(StanjeSnapshot).filter(StanjeSnapshot.snapshot_id == stari.id).delete()
                db.query(Dogadjaj).filter(Dogadjaj.snapshot_id == stari.id).delete()
                db.delete(stari)
            db.flush()

        # 1) novi snapshot (flush da dobijemo id za naziv filea). aktivni se postavlja NA KRAJU
        #    na najnoviji po datumu - tako dodavanje STAROG exporta (backfill povijesti) ne
        #    pomakne dashboard s aktualnog stanja.
        snap = Snapshot(datum_exporta=datum_exporta, izvor_naziv=filename,
                        ucitano_at=datetime.now(), aktivan=False)
        db.add(snap)
        db.flush()

        # 2) spremi sirovi file kao uploads/<id>_<ime>.xlsx
        ime = f"{snap.id}_{_sigurno_ime(filename)}"
        putanja = uploads_dir() / ime
        putanja.write_bytes(data)
        spremljeni_file = putanja
        snap.datoteka = str(Path("uploads") / ime)

        # 3) Dogadjaj se drze PO SNAPSHOTU (svaki snapshot svoje) - NE globalni wipe. Stari
        #    isti-datum snapshot je vec obrisan u koraku 0 (dedup) zajedno sa svojim dogadjajima.
        #    (Prije se brisalo sve pa reinsertalo za "aktivni"; ali kod bulk uvoza zadnji obradjeni
        #    file != aktivni po datumu, pa su dogadjaji ostajali vezani uz krivi snapshot i
        #    projekcija je nestajala. Po-snapshotu je jednostavno i tocno.)
        #    v3: prolazi se kroz SVE materijale iz exporta (~1300), ne samo pracene - da se
        #    moze pretraziti i nacrtati graf za bilo koju sifru. `artikl_id` je None za one
        #    izvan popisa pracenih; `fali` se racuna samo za pracene (ostali nemaju minimum).
        redovi_stanja, redovi_dogadjaja = [], []
        for sifra, red in sklad.items():
            a = artikl_po_sifri.get(sifra)
            stanje = f(red.iloc[pauk.C_STANJE])
            nak_rn = f(red.iloc[pauk.C_NAK_RN])
            nak_nar = f(red.iloc[pauk.C_NAK_NAR])

            fali = izracunaj_fali(a.min_tip, a.min_broj, nak_nar, suma_krpe) if a else 0.0
            dogadjaji = svi_dogadjaji.get(sifra, [])
            proj = projekcija_puna(stanje, dogadjaji, danas)

            zavrsna = stanje + sum(d["kolicina"] for d in dogadjaji)
            odstupa = provjeri_odstupanje(zavrsna, nak_nar)

            redovi_stanja.append(dict(
                snapshot_id=snap.id, artikl_id=(a.id if a else None), sifra=sifra,
                naziv=str(red.iloc[pauk.C_NAZIV]), dobavljac=str(red.iloc[pauk.C_DOBAV]),
                stanje=stanje, nak_rn=nak_rn, nak_nar=nak_nar, fali=fali,
                status=proj["status"],
                prvi_pad_datum=proj["datum"].to_pydatetime() if proj["datum"] is not None else None,
                prvi_pad_dani=proj["dani"],
                oporavlja_li_se=proj["oporavlja_li_se"],
                datum_oporavka=(proj["datum_oporavka"].to_pydatetime()
                                if proj["datum_oporavka"] is not None else None),
                odstupa_od_erp=odstupa,
            ))
            for dd in dogadjaji:
                redovi_dogadjaja.append(dict(
                    snapshot_id=snap.id, artikl_id=(a.id if a else None), sifra=sifra,
                    datum=dd["datum"].to_pydatetime(),
                    kolicina=dd["kolicina"], tip=dd["tip"], izvor=dd["izvor"]))

        # bulk insert (ORM add() po retku bi na ~3300 redaka x 62 exporta bio presporo)
        if redovi_stanja:
            db.execute(insert(StanjeSnapshot), redovi_stanja)
        if redovi_dogadjaja:
            db.execute(insert(Dogadjaj), redovi_dogadjaja)

        _postavi_aktivni_najnoviji(db)
        db.commit()
        return snap
    except Exception:
        db.rollback()
        if spremljeni_file is not None:
            try:
                spremljeni_file.unlink()
            except OSError:
                pass
        raise


def _postavi_aktivni_najnoviji(db: Session) -> None:
    """Aktivni (prikazan na dashboardu) = snapshot s NAJKASNIJIM datum_exporta (fallback
    ucitano_at). Tako dodavanje starijeg exporta ne pomakne dashboard s aktualnog stanja."""
    snap = db.scalar(select(Snapshot).where(Snapshot.datum_exporta.is_not(None))
                     .order_by(Snapshot.datum_exporta.desc()).limit(1))
    if snap is None:
        snap = db.scalar(select(Snapshot).order_by(Snapshot.ucitano_at.desc()).limit(1))
    if snap is not None:
        db.query(Snapshot).update({Snapshot.aktivan: False})
        snap.aktivan = True


def preracunaj_iz_arhive(db: Session) -> dict:
    """Ponovno izracuna SVE snapshote iz sirovih .xlsx spremljenih u uploads/, bez ponovnog
    uploada. Koristi se kad se promijeni logika izracuna (npr. prelazak na spremanje svih
    materijala) - povijest ostaje ista jer su izvorni exporti sacuvani.
    Postojeci Snapshot redovi se ZADRZAVAJU (datumi/datoteke), samo se derivirani podaci
    (StanjeSnapshot/Dogadjaj) obrisu i ponovno izracunaju."""
    rez = {"preracunato": 0, "greske": []}
    snapshoti = list(db.scalars(select(Snapshot).order_by(Snapshot.datum_exporta)).all())
    artikli = list(db.scalars(select(Artikl)).all())
    artikl_po_sifri = {a.sifra: a for a in artikli}

    for snap in snapshoti:
        if not snap.datoteka or not Path(snap.datoteka).exists():
            rez["greske"].append((snap.izvor_naziv, "nema spremljene datoteke"))
            continue
        try:
            data = Path(snap.datoteka).read_bytes()
            df = pauk.ucitaj_i_normaliziraj(data)
            danas = (pd.Timestamp(snap.datum_exporta.date()) if snap.datum_exporta
                     else pd.Timestamp(snap.ucitano_at.date()))
            sklad = pauk.sklad_po_sifri(df)
            svi_dog = dogadjaji_po_sifri(pauk.df_nalozi(df), pauk.df_narudzbe(df))
            nak_nar_po_sifri = {a.sifra: f(sklad[a.sifra].iloc[pauk.C_NAK_NAR])
                                for a in artikli if a.sifra in sklad}
            suma_krpe = izracunaj_suma_krpe(artikli, nak_nar_po_sifri)

            db.query(StanjeSnapshot).filter(StanjeSnapshot.snapshot_id == snap.id).delete()
            db.query(Dogadjaj).filter(Dogadjaj.snapshot_id == snap.id).delete()

            stanja, dogadjaji_r = [], []
            for sifra, red in sklad.items():
                a = artikl_po_sifri.get(sifra)
                stanje = f(red.iloc[pauk.C_STANJE])
                nak_nar = f(red.iloc[pauk.C_NAK_NAR])
                dog = svi_dog.get(sifra, [])
                proj = projekcija_puna(stanje, dog, danas)
                stanja.append(dict(
                    snapshot_id=snap.id, artikl_id=(a.id if a else None), sifra=sifra,
                    naziv=str(red.iloc[pauk.C_NAZIV]), dobavljac=str(red.iloc[pauk.C_DOBAV]),
                    stanje=stanje, nak_rn=f(red.iloc[pauk.C_NAK_RN]), nak_nar=nak_nar,
                    fali=(izracunaj_fali(a.min_tip, a.min_broj, nak_nar, suma_krpe) if a else 0.0),
                    status=proj["status"],
                    prvi_pad_datum=proj["datum"].to_pydatetime() if proj["datum"] is not None else None,
                    prvi_pad_dani=proj["dani"], oporavlja_li_se=proj["oporavlja_li_se"],
                    datum_oporavka=(proj["datum_oporavka"].to_pydatetime()
                                    if proj["datum_oporavka"] is not None else None),
                    odstupa_od_erp=provjeri_odstupanje(
                        stanje + sum(d["kolicina"] for d in dog), nak_nar),
                ))
                for dd in dog:
                    dogadjaji_r.append(dict(
                        snapshot_id=snap.id, artikl_id=(a.id if a else None), sifra=sifra,
                        datum=dd["datum"].to_pydatetime(), kolicina=dd["kolicina"],
                        tip=dd["tip"], izvor=dd["izvor"]))

            if stanja:
                db.execute(insert(StanjeSnapshot), stanja)
            if dogadjaji_r:
                db.execute(insert(Dogadjaj), dogadjaji_r)
            db.commit()
            rez["preracunato"] += 1
        except Exception as e:
            db.rollback()
            rez["greske"].append((snap.izvor_naziv, str(e)))

    _postavi_aktivni_najnoviji(db)
    db.commit()
    return rez


def uvezi_iz_mape(db: Session, mapa: Path) -> dict:
    """Uveze SVE PAUK exporte iz mape (naziv sadrzi 'STANJA MATERIJALA', .xlsx) cije
    datum_exporta jos nije u arhivi - za brzo popunjavanje povijesti. Redoslijed obrade je
    po datumu (stari prvi); aktivni ostaje najnoviji (obradi_upload to sredi). Vraca
    {uvezeno:[], preskoceno:[], greske:[(ime,razlog)]}."""
    rez = {"uvezeno": [], "preskoceno": [], "greske": []}
    if not mapa.exists() or not mapa.is_dir():
        rez["greske"].append((str(mapa), "mapa ne postoji"))
        return rez

    postojeci = {s.datum_exporta for s in db.scalars(select(Snapshot)).all() if s.datum_exporta}

    # kandidati: .xlsx s 'stanja materijala' u nazivu; poredaj po datumu iz peek-a (stari prvi)
    kandidati = []
    for fpath in mapa.glob("*.xlsx"):
        if "stanja materijala" not in fpath.name.lower():
            continue
        try:
            data = fpath.read_bytes()
        except OSError as e:
            rez["greske"].append((fpath.name, f"ne mogu procitati: {e}"))
            continue
        datum = pauk.peek_datum(data)
        if datum is None:
            rez["greske"].append((fpath.name, "necitljiv datum exporta"))
            continue
        kandidati.append((datum, fpath.name, data))

    for datum, ime, data in sorted(kandidati, key=lambda x: x[0]):
        if datum in postojeci:
            rez["preskoceno"].append(ime)
            continue
        try:
            obradi_upload(db, ime, data)
            postojeci.add(datum)
            rez["uvezeno"].append(ime)
        except Exception as e:
            rez["greske"].append((ime, str(e)))
    return rez


def aktivni_snapshot(db: Session) -> Snapshot | None:
    """Trenutno aktivni snapshot (zadnji upload, osim ako je korisnik rucno aktivirao stariji)."""
    snap = db.scalar(select(Snapshot).where(Snapshot.aktivan == True))  # noqa: E712
    if snap is None:
        snap = db.scalar(select(Snapshot).order_by(Snapshot.ucitano_at.desc()).limit(1))
    return snap


def _snapshot_datum(snap: Snapshot) -> datetime:
    """Datum koji reprezentira snapshot na vremenskoj osi: datum exporta, fallback ucitano_at."""
    return snap.datum_exporta or snap.ucitano_at


def povijest_stanja(db: Session, sifra: str) -> list[dict]:
    """Stvarno IZMJERENO stanje kroz sve uploade za jednu sifru - jedan podatak po snapshotu
    na njegov datum exporta. Osnova povijesnog dijela kombinirane krivulje.
    Kljuc je SIFRA (ne artikl_id) - radi i za materijale izvan popisa pracenih."""
    redci = db.execute(
        select(Snapshot, StanjeSnapshot)
        .join(StanjeSnapshot, StanjeSnapshot.snapshot_id == Snapshot.id)
        .where(StanjeSnapshot.sifra == sifra)
    ).all()
    tocke = [{"datum": _snapshot_datum(s), "stanje": ss.stanje, "nak_nar": ss.nak_nar}
             for s, ss in redci]
    tocke.sort(key=lambda t: t["datum"])
    return tocke


def kombinirana_krivulja(db: Session, sifra: str, aktivni: Snapshot,
                         stanje_akt: StanjeSnapshot | None) -> dict:
    """Spaja STVARNU POVIJEST (izmjereno stanje kroz proslе uploade) + PROJEKCIJU unaprijed
    (od zadnjeg stanja, iz dogadjaja aktivnog snapshota) u jednu vremensku os. Zadnja
    povijesna tocka i prva projekcijska su isti (x=danas, y=zadnje stanje) -> spoj bez rupe.
    Vraca {povijest:[{x,y}], projekcija:[{x,y}], danas:iso} za Chart.js."""
    povijest_raw = povijest_stanja(db, sifra)
    danas = pd.Timestamp(_snapshot_datum(aktivni).date())

    # povijesne tocke STROGO prije danas (zadnja=danas dolazi iz projekcije, da se spoje)
    povijest = [{"x": t["datum"].strftime("%Y-%m-%d"), "y": round(t["stanje"], 2)}
                for t in povijest_raw if pd.Timestamp(t["datum"].date()) < danas]

    projekcija: list[dict] = []
    if stanje_akt is not None:
        dogadjaji = list(db.scalars(
            select(Dogadjaj).where(Dogadjaj.sifra == sifra,
                                    Dogadjaj.snapshot_id == aktivni.id)
        ).all())
        dog_dict = [{"datum": pd.Timestamp(d.datum), "kolicina": d.kolicina} for d in dogadjaji]
        projekcija = tocke_grafa(stanje_akt.stanje, dog_dict, danas)
        # spoji: zadnja povijesna tocka = prva projekcijska
        if povijest:
            povijest.append({"x": danas.strftime("%Y-%m-%d"), "y": round(stanje_akt.stanje, 2)})

    return {"povijest": povijest, "projekcija": projekcija, "danas": danas.strftime("%Y-%m-%d")}
