"""Pocetni popis pracenih artikala - prenesen iz desktop alata
(Arhiva skripta\\Tjedna usklada\\...\\UskaldaGEN.py, ARTIKLI_BASE), 63 artikla / 13 kategorija.
Seedano jednom u praznu bazu (main.py zove seed_artikli_ako_prazno() nakon create_all,
isti obrazac kao _seed_admin() u Reklamacije-app)."""
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.modules.nabava.models import Artikl

# (kategorija, [(sifra, min), ...]) - min je broj, "POSITIVE" ili "COMB_3"
KATEGORIJE_BASE = [
    ("SREDSTVA ZA PRANJE I PRIPREMU", [
        ("5020103010400001", 250),
        ("50201080200001", 50),
        ("502010301010100017", 50),
        ("502010301010100012", 10),
    ]),
    ("OFFSETNE PLOCE", [
        ("501050100002", 500),
        ("501050100004", 150),
    ]),
    ("GUME I PRIBOR", [
        ("50201080100003", 50),
        ("502010301030100006", 15),
        ("502010301010100020", 40),
        ("50201010200005", 8),
        ("50201050200001", 20),
    ]),
    ("KRPE ZA PRANJE", [
        ("50201030200004", "COMB_3"),
        ("50201030200005", "COMB_3"),
    ]),
    ("PUDERI I LJEPENKE", [
        ("501010600001", 120),
        ("501010600002", 120),
        ("50101041200009", "POSITIVE"),
        ("50101041200008", "POSITIVE"),
        ("50101040500067", "POSITIVE"),
    ]),
    ("LAKOVI", [
        ("501010702020100007", "POSITIVE"),
        ("5010107020200016", "POSITIVE"),
        ("5010107020200010", 250),
        ("5010107020200009", 400),
        ("50101010400006", 100),
    ]),
    ("CMYK BIJELI PAPIR", [
        ("5010101070100015", 180),
        ("5010101070100016", 90),
        ("5010101070100017", 90),
        ("5010101070100014", 180),
        ("5010101070100005", 80),
    ]),
    ("CMYK ALU PAPIR", [
        ("5010101020100006", 20),
        ("5010101020100008", 20),
        ("5010101020100007", 50),
        ("5010101020100005", 180),
    ]),
    ("BIJELA BOJA", [
        ("5010101020200003", 300),
        ("5010101020200016", 450),
    ]),
    ("FOLIJE", [
        ("50101020100117", "POSITIVE"),
        ("50101020100114", "POSITIVE"),
        ("50101020100113", "POSITIVE"),
        ("50101020100112", "POSITIVE"),
        ("50101020100118", "POSITIVE"),
        ("50101020100115", "POSITIVE"),
    ]),
    ("KUTIJE", [
        ("50102010100030", 10000),
        ("50102010100001", 10000),
        ("50102010100027", 10000),
        ("50102010100028", 10000),
        ("50102010100037", 3000),
        ("50102010200002", 2000),
        ("50102010200052", 2000),
        ("50102010100003", 500),
        ("50102010100016", 200),
        ("50102010100015", 200),
        ("50102010100036", 100),
        ("50102010100035", 100),
    ]),
]


def seed_artikli_ako_prazno() -> None:
    db = SessionLocal()
    try:
        if (db.scalar(select(func.count(Artikl.id))) or 0) > 0:
            return
        redoslijed = 10
        for kategorija, stavke in KATEGORIJE_BASE:
            for sifra, min_v in stavke:
                min_tip = min_v if min_v in ("POSITIVE", "COMB_3") else "BROJ"
                min_broj = float(min_v) if min_tip == "BROJ" else None
                db.add(Artikl(kategorija=kategorija, redoslijed=redoslijed, sifra=sifra,
                              min_tip=min_tip, min_broj=min_broj))
                redoslijed += 10
        db.commit()
        print(f"[Nabava] Seedano {sum(len(s) for _, s in KATEGORIJE_BASE)} artikala.")
    finally:
        db.close()
