"""Test kljucnog scenarija iz razgovora s korisnikom: boja na 1000kg, radni nalog je vuce
na negativu, ali narudzba stize PRIJE toga i vrati je iznad minimuma -> ne treba naruciti,
i znacka NE smije biti crveni alarm. Ovo je nova, netestirana logika (dolazak robe), pa je
ovaj test najvazniji korak provjere."""
import pandas as pd

from app.modules.nabava import service


def _dog(datum: str, kolicina: float, tip: str):
    return {"datum": pd.Timestamp(datum), "kolicina": kolicina, "tip": tip, "izvor": None}


def test_privremeni_pad_koji_se_oporavi_nije_alarm():
    danas = pd.Timestamp("2026-07-21")
    stanje = 1000.0
    dogadjaji = [
        _dog("2026-07-25", -1200, "TROSENJE"),  # pad na -200
        _dog("2026-07-28", +1400, "DOLAZAK"),   # narudzba vrati na +1200
    ]
    proj = service.projekcija_puna(stanje, dogadjaji, danas)

    assert proj["status"] == "PADA"
    assert proj["oporavlja_li_se"] is True
    assert proj["datum_oporavka"] == pd.Timestamp("2026-07-28")

    stil = service.stil_statusa(proj["status"], proj["dani"], proj["oporavlja_li_se"])
    # mirna (info/plava) znacka, NE crveni/narancasti alarm (critical/serious)
    assert stil["tip"] == "info"
    assert stil["tip"] not in ("critical", "serious")
    assert "oporavak" in stil["oznaka"]


def test_trajni_pad_bez_oporavka_je_alarm():
    danas = pd.Timestamp("2026-07-21")
    stanje = 1000.0
    dogadjaji = [_dog("2026-07-23", -1200, "TROSENJE")]  # pad na -200, nista ne stize
    proj = service.projekcija_puna(stanje, dogadjaji, danas)

    assert proj["status"] == "PADA"
    assert proj["oporavlja_li_se"] is False
    stil = service.stil_statusa(proj["status"], proj["dani"], proj["oporavlja_li_se"])
    assert stil["tip"] == "critical"  # pada za 2 dana, bez oporavka -> crveno


def test_dolazak_prije_pada_nikad_ne_padne():
    danas = pd.Timestamp("2026-07-21")
    stanje = 100.0
    dogadjaji = [
        _dog("2026-07-25", +5000, "DOLAZAK"),
        _dog("2026-07-28", -1200, "TROSENJE"),  # nakon dolaska bilanca je 3900, ne pada
    ]
    proj = service.projekcija_puna(stanje, dogadjaji, danas)
    assert proj["status"] == "-"


def test_vec_ispod_nule_s_buducom_narudzbom():
    danas = pd.Timestamp("2026-07-21")
    stanje = -50.0
    dogadjaji = [_dog("2026-07-24", +200, "DOLAZAK")]
    proj = service.projekcija_puna(stanje, dogadjaji, danas)
    assert proj["status"] == "ISPOD0"
    assert proj["oporavlja_li_se"] is True


def test_kasni_kad_je_uzrok_pada_u_proslosti():
    danas = pd.Timestamp("2026-07-21")
    stanje = 100.0
    # radni nalog s rokom u proslosti koji povlaci ispod nule
    dogadjaji = [_dog("2026-07-18", -150, "TROSENJE")]
    proj = service.projekcija_puna(stanje, dogadjaji, danas)
    assert proj["status"] == "KASNI"
    assert proj["dani"] < 0


def test_tocke_grafa_kumulativna_bilanca():
    danas = pd.Timestamp("2026-07-21")
    tocke = service.tocke_grafa(1000.0, [
        _dog("2026-07-25", -1200, "TROSENJE"),
        _dog("2026-07-28", +1400, "DOLAZAK"),
    ], danas)
    assert tocke[0] == {"x": "2026-07-21", "y": 1000.0}
    assert tocke[1] == {"x": "2026-07-25", "y": -200.0}
    assert tocke[2] == {"x": "2026-07-28", "y": 1200.0}


def test_tocke_grafa_prikvaci_zakasnjeli_dogadjaj_na_danas():
    danas = pd.Timestamp("2026-07-21")
    tocke = service.tocke_grafa(100.0, [_dog("2026-07-18", -30, "TROSENJE")], danas)
    # zakasnjeli dogadjaj (18.07) se za crtanje prikvaci na danas (21.07), ne u proslost
    assert tocke[1]["x"] == "2026-07-21"
    assert tocke[1]["y"] == 70.0


def test_fali_racun():
    assert service.izracunaj_fali("BROJ", 500.0, 300.0, 0.0) == 200.0
    assert service.izracunaj_fali("BROJ", 500.0, 600.0, 0.0) == 0.0
    assert service.izracunaj_fali("POSITIVE", None, 0.0, 0.0) == 0.01   # treba naruciti
    assert service.izracunaj_fali("POSITIVE", None, 5.0, 0.0) == 0.0
    assert service.izracunaj_fali("COMB_3", None, 0.0, 2.0) == 1.0      # zbroj 2 < 3
    assert service.izracunaj_fali("COMB_3", None, 0.0, 3.0) == 0.0      # zbroj 3 = OK


# ─── v2: povijest + kombinirana krivulja (DB) ───────────────────────────────

from datetime import datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.modules.nabava.models import Artikl, Dogadjaj, Snapshot, StanjeSnapshot


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(bind=eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_povijest_i_kombinirana_krivulja_spoj_bez_rupe(db):
    a = Artikl(kategorija="TEST", redoslijed=10, sifra="X1", min_tip="BROJ", min_broj=100)
    db.add(a); db.flush()

    # dva uploada: stariji (500) i aktivni (300)
    s1 = Snapshot(datum_exporta=datetime(2026, 7, 1), izvor_naziv="a.xlsx",
                  ucitano_at=datetime(2026, 7, 1), aktivan=False)
    s2 = Snapshot(datum_exporta=datetime(2026, 7, 21), izvor_naziv="b.xlsx",
                  ucitano_at=datetime(2026, 7, 21), aktivan=True)
    db.add_all([s1, s2]); db.flush()
    db.add(StanjeSnapshot(snapshot_id=s1.id, artikl_id=a.id, sifra="X1", stanje=500, nak_nar=500))
    ss2 = StanjeSnapshot(snapshot_id=s2.id, artikl_id=a.id, sifra="X1", stanje=300, nak_nar=-100)
    db.add(ss2)
    # projekcija iz aktivnog: trosenje -400 @ 25.07 -> pada na -100
    db.add(Dogadjaj(snapshot_id=s2.id, artikl_id=a.id, sifra="X1",
                    datum=datetime(2026, 7, 25), kolicina=-400, tip="TROSENJE"))
    db.flush()

    pov = service.povijest_stanja(db, a.id)
    assert [round(p["stanje"]) for p in pov] == [500, 300]

    kr = service.kombinirana_krivulja(db, a.id, s2, ss2)
    # povijest zavrsava na danas s trenutnim stanjem; projekcija pocinje na istoj tocki
    assert kr["danas"] == "2026-07-21"
    assert kr["povijest"][-1] == {"x": "2026-07-21", "y": 300.0}
    assert kr["projekcija"][0] == {"x": "2026-07-21", "y": 300.0}
    # projekcija nastavlja u buducnost i pada
    assert kr["projekcija"][-1] == {"x": "2026-07-25", "y": -100.0}


def test_dedup_istog_exporta_ne_duplicira_povijest(db, tmp_path, monkeypatch):
    """Re-upload istog PAUK exporta (isti datum_exporta) NE smije dodati duplu povijesnu
    tocku - zamjenjuje postojeci snapshot. Razliciti datumi ostaju zasebni."""
    monkeypatch.chdir(tmp_path)  # uploads/ ide u temp
    a = Artikl(kategorija="TEST", redoslijed=10, sifra="5010101070100015", min_tip="BROJ", min_broj=100)
    db.add(a); db.commit()

    import os
    dl = r"C:\Users\Tehnolog\Downloads"
    fn = "IZVJEŠĆE STANJA MATERIJALA 21.07.2026. 08_34.xlsx"
    put = os.path.join(dl, fn)
    if not os.path.exists(put):
        pytest.skip("nema stvarnog PAUK exporta za ovaj test")
    data = open(put, "rb").read()

    service.obradi_upload(db, fn, data)
    service.obradi_upload(db, fn, data)  # isti export drugi put
    assert db.scalar(select(func.count(Snapshot.id))) == 1  # NE 2
    assert len(service.povijest_stanja(db, a.id)) == 1       # jedna povijesna tocka


def test_stariji_export_ne_krade_aktivni(db, tmp_path, monkeypatch):
    """Nakon uploada novog pa STARIJEG exporta, aktivni (dashboard) mora ostati NOVIJI -
    dodavanje stare 'tablice' (backfill povijesti) ne smije pomaknuti dashboard."""
    monkeypatch.chdir(tmp_path)
    db.add(Artikl(kategorija="T", redoslijed=10, sifra="501050100002", min_tip="BROJ", min_broj=100))
    db.commit()
    import os
    dl = r"C:\Users\Tehnolog\Downloads"
    novi = os.path.join(dl, "IZVJEŠĆE STANJA MATERIJALA 21.07.2026. 08_34.xlsx")
    stari = os.path.join(dl, "IZVJEŠĆE STANJA MATERIJALA 20.04.2026. 08_35.xlsx")
    if not (os.path.exists(novi) and os.path.exists(stari)):
        pytest.skip("nema stvarnih PAUK exporta za ovaj test")
    service.obradi_upload(db, "novi.xlsx", open(novi, "rb").read())
    service.obradi_upload(db, "stari.xlsx", open(stari, "rb").read())  # stariji datum, drugi
    akt = service.aktivni_snapshot(db)
    assert akt.datum_exporta == datetime(2026, 7, 21, 8, 34)  # noviji ostao aktivan


def test_pdf_izvoz(db):
    """PDF izvoz (rekapitulacija + detalji) se generira i vraca ispravne PDF bajtove."""
    a = Artikl(kategorija="TEST", redoslijed=10, sifra="X1", min_tip="BROJ", min_broj=100)
    db.add(a); db.flush()
    s = Snapshot(datum_exporta=datetime(2026, 7, 21), izvor_naziv="x.xlsx",
                 ucitano_at=datetime(2026, 7, 21), aktivan=True)
    db.add(s); db.flush()
    db.add(StanjeSnapshot(snapshot_id=s.id, artikl_id=a.id, sifra="X1", naziv="Test artikl",
                          dobavljac="Dobav d.o.o.", stanje=50, nak_nar=50, fali=50,
                          status="PADA", prvi_pad_dani=5))
    db.commit()
    from app.modules.nabava import pdf as pdf_modul
    data, naziv = pdf_modul.generiraj_pdf(db)
    assert data[:4] == b"%PDF"        # ispravan PDF
    assert len(data) > 1000
    assert naziv.endswith(".pdf")


def test_kombinirana_bez_povijesti_samo_projekcija(db):
    a = Artikl(kategorija="TEST", redoslijed=10, sifra="X2", min_tip="BROJ", min_broj=100)
    db.add(a); db.flush()
    s = Snapshot(datum_exporta=datetime(2026, 7, 21), izvor_naziv="b.xlsx",
                 ucitano_at=datetime(2026, 7, 21), aktivan=True)
    db.add(s); db.flush()
    ss = StanjeSnapshot(snapshot_id=s.id, artikl_id=a.id, sifra="X2", stanje=200, nak_nar=200)
    db.add(ss); db.flush()

    kr = service.kombinirana_krivulja(db, a.id, s, ss)
    # samo jedan snapshot -> nema povijesnih tocaka prije danas, projekcija krece od stanja
    assert kr["povijest"] == []
    assert kr["projekcija"][0] == {"x": "2026-07-21", "y": 200.0}
