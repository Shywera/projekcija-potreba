from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Artikl(Base):
    """Konfiguracija - koje sifre pratimo, u kojoj kategoriji i s kojim minimumom.
    Zamjena za staru ARTIKLI_BASE listu + Tkinter SifreEditor iz desktop alata."""
    __tablename__ = "artikl"
    __table_args__ = (UniqueConstraint("sifra", name="uq_artikl_sifra"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kategorija: Mapped[str] = mapped_column(String(100), index=True)
    redoslijed: Mapped[int] = mapped_column(Integer, default=0, index=True)
    sifra: Mapped[str] = mapped_column(String(50), index=True)

    # min_tip: "BROJ" (usporeduje se min_broj s nak_nar) | "POSITIVE" (nak_nar mora biti > 0)
    # | "COMB_3" (zbroj nak_nar svih COMB_3 sifri mora biti >= 3 - npr. krpe za pranje)
    min_tip: Mapped[str] = mapped_column(String(10), default="BROJ")
    min_broj: Mapped[float | None] = mapped_column(Float, nullable=True)

    napomena: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Snapshot(Base):
    """Jedan upload PAUK exporta. v2: POVIJEST - jedan red po uploadu (ne upsert kao v1),
    tako da se stari exporti mogu pregledati (arhiva) i kombinirati u povijesni graf.
    `datoteka` = relativna putanja spremljenog sirovog .xlsx (uploads/), `aktivan` = je li
    ovo trenutni prikaz na dashboardu."""
    __tablename__ = "snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    datum_exporta: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    izvor_naziv: Mapped[str] = mapped_column(String(300))
    ucitano_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    datoteka: Mapped[str | None] = mapped_column(String(400), nullable=True)
    aktivan: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class StanjeSnapshot(Base):
    """Izracunati brojevi po (snapshot, MATERIJAL). AKUMULIRA se kroz sve uploade - dashboard
    cita retke aktivnog snapshota, povijesni graf cita stanje kroz sve snapshote za jednu sifru.

    v3: sprema se za SVE materijale iz exporta (~1300), ne samo za 52 pracena - da se moze
    pretraziti i nacrtati graf za bilo koju sifru. Zato je `artikl_id` NULLABLE (materijal
    koji nije na popisu pracenih nema Artikl red); pravi kljuc je `sifra`.
    """
    __tablename__ = "stanje_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshot.id"), index=True)
    artikl_id: Mapped[int | None] = mapped_column(ForeignKey("artikl.id"), index=True, nullable=True)
    sifra: Mapped[str] = mapped_column(String(50), index=True)

    naziv: Mapped[str | None] = mapped_column(String(300), nullable=True)
    dobavljac: Mapped[str | None] = mapped_column(String(150), nullable=True)

    stanje: Mapped[float] = mapped_column(Float, default=0.0)
    nak_rn: Mapped[float] = mapped_column(Float, default=0.0)
    nak_nar: Mapped[float] = mapped_column(Float, default=0.0)
    fali: Mapped[float] = mapped_column(Float, default=0.0)

    # status: "-" | "ISPOD0" | "KASNI" | "PADA" (iz projekcija_puna, PUNA - trosenje+dolazak)
    status: Mapped[str] = mapped_column(String(10), default="-")
    prvi_pad_datum: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    prvi_pad_dani: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oporavlja_li_se: Mapped[bool] = mapped_column(Boolean, default=False)
    datum_oporavka: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # obrambena provjera: zavrsna bilanca simulacije nasuprot nak_nar iz PAUK exporta
    odstupa_od_erp: Mapped[bool] = mapped_column(Boolean, default=False)


class Dogadjaj(Base):
    """Vremenska linija (trosenje + dolazak) po sifri - osnova za projekciju/graf i transparency
    tablicu na detalj-stranici. Vezana uz snapshot iz kojeg je izracunata (PO SNAPSHOTU, svaki
    svoje - NE globalni wipe; detalj koristi dogadjaje AKTIVNOG snapshota). Vidi napomenu u
    service.obradi_upload zasto po-snapshotu (bulk uvoz je lomio 'samo aktivni' pristup)."""
    __tablename__ = "dogadjaj"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshot.id"), index=True)
    # nullable - dogadjaji se biljeze za SVE materijale, i one izvan popisa pracenih (v3)
    artikl_id: Mapped[int | None] = mapped_column(ForeignKey("artikl.id"), index=True, nullable=True)
    sifra: Mapped[str] = mapped_column(String(50), index=True)

    datum: Mapped[datetime] = mapped_column(DateTime)
    kolicina: Mapped[float] = mapped_column(Float)  # predznak: - trosenje, + dolazak
    tip: Mapped[str] = mapped_column(String(10))     # TROSENJE | DOLAZAK
    izvor: Mapped[str | None] = mapped_column(String(50), nullable=True)  # br. RN ili br. narudzbe
