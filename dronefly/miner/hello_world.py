from pyinaturalist import pprint
from pyinaturalist_convert import load_fts_taxa, TaxonAutocompleter

load_fts_taxa(languages=['english', 'german'])
ta = TaxonAutocompleter()
searches = [
    [['aves'], {}],
    [['flughund'], {'language': 'de'}]
]
taxa = []
for args, kwargs in searches:
    mat = ta.search(*args, **kwargs)
    if mat:
        taxa.append(mat[0])
for taxon in taxa:
    print(taxon.to_json)
    pprint(taxon)
