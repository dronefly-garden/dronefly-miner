from platformdirs import user_data_dir
import os

from pyinaturalist import PathOrStr, pprint
from pyinaturalist_convert import DWCA_OBS_CSV, DWCA_TAXON_CSV, CSVProgress, create_tables, download_dwca_observations, download_dwca_taxa, enable_logging, get_db_taxa, load_dwca_observations, load_dwca_taxa, load_fts_taxa, aggregate_taxon_db, TaxonAutocompleter, vacuum_analyze

USER_DATA_PATH = os.path.join(user_data_dir(), "dronefly-miner")
DB_PATH = os.path.join(USER_DATA_PATH, 'observations.db')

def load_dwca_tables(db_path: PathOrStr = DB_PATH):
    """Download observation and taxonomy archives and load into a SQLite database.

    Args:
        db_path: Path to SQLite database

    A local version of this function from pyinaturalist_convert v0.9 that disables
    fast mode in vacuum_analyze step to avoid running out of memory (41GB consumed
    before being killed by OOM killer in one trial on 2026-09-16).
    """
    import sqlalchemy  # noqa: F401

    download_dwca_observations()
    download_dwca_taxa()
    with CSVProgress(DWCA_OBS_CSV, DWCA_TAXON_CSV) as progress:
        load_dwca_observations(db_path=db_path, progress=progress)
        load_dwca_taxa(db_path=db_path, progress=progress)
    create_tables(db_path, indexes=True)  # Create remaining tables that reference Taxon+Observation
    vacuum_analyze(['observation', 'taxon'], db_path, show_spinner=True)

def load_fts_data():
    """Load all full text search data.

    Downloads, builds, and indexes a local database from iNaturalist
    data exported to GBIF as DWCA-A taxonomy and observation data sets,
    supplemented by common names for all languages.
    """
    enable_logging()
    load_dwca_tables(db_path=DB_PATH)
    aggregate_taxon_db(db_path=DB_PATH)
    load_fts_taxa(db_path=DB_PATH, languages='all')

def taxon_autocomplete(text: str, language='en'):
    """Autocomplete taxa matching text.

    Autocompletion results are retrieved with a fast lookup against the
    local full-text indexed database.
    """
    ta = TaxonAutocompleter(db_path=DB_PATH)
    fts_taxa = ta.search(text, language=language)
    db_taxa = None
    if fts_taxa:
        fts_taxon_ids = [t.id for t in fts_taxa]
        db_taxa = get_db_taxa(db_path=DB_PATH, ids=fts_taxon_ids)
    return db_taxa

def ta(text: str, language='en'):
    """Do one taxon_autocomplete and pretty-print the top hit.

    A convenience method to play with fta searches.
    """
    db_taxa = taxon_autocomplete(text, language=language)
    if db_taxa:
        pprint(next(db_taxa))
    else:
        print(f"Not found: {text}")
