from platformdirs import user_data_dir
import os
import shutil

from pyinaturalist import pprint
from pyinaturalist_convert import enable_logging, get_db_taxa, load_dwca_tables, load_fts_taxa, aggregate_taxon_db, TaxonAutocompleter

USER_DATA_PATH = os.path.join(user_data_dir(), "dronefly-miner")
DB_PATH = os.path.join(USER_DATA_PATH, 'observations.db')
DWCA_DB_PATH = os.path.join(USER_DATA_PATH, 'observations.dwca.db')
AGG_DB_PATH = os.path.join(USER_DATA_PATH, 'observations.agg.db')

def load_fts_data():
    """Load all full text search data.

    Downloads, builds, and indexes a local database from iNaturalist
    data exported to GBIF as DWCA-A taxonomy and observation data sets,
    supplemented by common names for all languages.
    """
    enable_logging()
    try:
        load_dwca_tables(db_path=DB_PATH)
    except Exception as err:
        print(err)
    shutil.copy(DB_PATH, DWCA_DB_PATH)

    try:
        aggregate_taxon_db(db_path=DB_PATH)
    except Exception as err:
        print(err)
    shutil.copy(DB_PATH, AGG_DB_PATH)

    try:
        load_fts_taxa(db_path=DB_PATH, languages='all')
    except Exception as err:
        print(err)

def taxon_autocomplete(text: str, language='en'):
    """Autocomplete taxa matching text.

    Autocompletion results are retrieved with a fast lookup against the
    local full-text indexed database.
    """
    ta = TaxonAutocompleter(db_path=DB_PATH)
    fts_taxa = ta.search(text, language=language)
    db_taxa = None
    if fts_taxa:
        fts_taxon = fts_taxa[0]
        db_taxa = get_db_taxa(db_path=DB_PATH, ids=[fts_taxon.id])
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
