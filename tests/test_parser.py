"""Tests for siphon/core/parser.py. Run them with:   pytest"""
from pathlib import Path

import pytest

from siphon_app.core.fetcher import FetchedPage
from siphon_app.core.parser import charset_from_content_type, parse_page, parse_tables

FIXTURES = Path(__file__).parent / "fixtures"

def one(html: str):
    """Parse html that contains exactly on table and return it."""
    tables = parse_tables(html)
    assert len(tables) == 1
    return tables[0]

#the page that exposed the bugs in the old scraper
def test_prices_page_keeps_every_row():
    tables = parse_tables((FIXTURES / "prices.html").read_bytes(), source_url="http://x.test/p")
    assert len(tables) == 1
    table = tables[0]
    assert table.name == "Prices"
    assert table.headers == ["Name", "Price", "Cap", "Change"]
    assert table.n_rows == 5
    assert table.source_url == "http://x.test/p"
    assert not table.is_layout

def test_merged_cell_is_copied_into_each_column_it_covers():
    table = parse_tables((FIXTURES / "prices.html").read_bytes())[0]
    assert table.rows[3] == ["Merged cell row", "Merged cell row", "$1", "5%"]
    assert any("merged" in warning for warning in table.warnings)

#reading the HTML correctly
def test_omitted_end_tags():
    table = one("<table><tr><th>H1<th>H2<tr><td>a<td>b<tr><td>c<td>d</table>")
    assert table.headers == ["H1", "H2"]
    assert table.rows == [["a", "b"], ["c", "d"]]

def test_no_tables_gives_empty_list():
    assert parse_tables("<html><body><p>nothing here</p></body></html>") == []

def test_text_input_works_as_well_as_bytes():
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></table>"
    assert parse_tables(html)[0].rows == parse_tables(html.encode("utf-8"))[0].rows

def test_nested_table_rows_do_not_leak_into_the_outer_table():
    html = """
    <table id="outer-layout">
        <tr><th>Menu</th><th>Content</th></tr>
        <tr><td>Left</td><td>
        <table><tr><th>X</th><th>Y</th></tr><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></table>
        </td></tr>
    </table>"""
    outer, inner = parse_tables(html)
    assert outer.is_layout and any("another table" in w for w in outer.warnings)
    assert outer.n_rows == 1 # only its own row, not the inner table's 3 rows
    assert outer.rows[0][0] == "Left"
    assert inner.headers == ["X", "Y"]
    assert inner.rows == [["1", "2"], ["3", "4"]] # exactly the inner rows, nothing from the outer
    assert not inner.is_layout

def test_cell_text_is_tidied():
    table = one("""
    <table>
        <tr><th>A</th><th>B</th></tr>
        <tr><td>Line one<br>Line two</td><td><a href="#">Foo</a>, <a href="#">Bar</a></td></tr>
        <tr><td>a&nbsp;&nbsp;   b</td><td><p>Para one</p><p>Para two</p></td></tr>
        <tr><td>x<script>var secret = 1;</script><style>.a{}</style>y</td><td>12<span>34</span></td></tr>
        <tr><td>p<noscript>Please enable JavaScript</noscript>q</td><td>ok</td></tr>
    </table>""")
    assert table.rows[0] == ["Line one Line two", "Foo, Bar"]
    assert table.rows[1] == ["a b", "Para one Para two"]
    assert table.rows[2] == ["xy", "1234"]              # code removed; inline tags don't add spaces
    assert table.rows[3] == ["pq", "ok"]                # "enable JavaScript" notices are not data

def test_zero_width_spaces_are_removed():
    table = one("<table><tr><th>A</th><th>B</th></tr><tr><td>a\u200bb</td><td>1</td></tr><tr><td>2</td><td>3</td></tr></table>")
    assert table.rows[0] == ["ab", "1"]

def test_currency_signs_count_as_numbers_when_guessing_headers():
    # A first row made only of money amounts is data, so the columns get numbered.
    table = one("<table><tr><td>\u20ac5</td><td>\u00a37</td><td>\u00a52</td><td>\u20b99</td></tr><tr><td>1</td><td>2</td><td>3</td><td>4</td></tr></table>")
    assert table.headers == ["Column 1", "Column 2", "Column 3", "Column 4"]
    assert table.n_rows == 2

def test_the_unicode_minus_counts_as_a_number_when_guessing_headers():
    table = one("<table><tr><td>\u22123</td><td>\u22124</td></tr><tr><td>1</td><td>2</td></tr></table>")
    assert table.headers == ["Column 1", "Column 2"]
    assert table.n_rows == 2

def test_tags_nested_inside_a_removed_noscript_are_fine():
    table = one("""
    <table>
        <tr><th>A</th><th>B</th></tr>
        <tr><td><noscript><div>Turn on <p>JavaScript</p><br></div></noscript>ok</td><td>1</td></tr>
        <tr><td>2</td><td>3</td></tr>
    </table>""")
    assert table.rows[0] == ["ok", "1"]

#merged cells
def test_rowspan_is_copied_down():
    table = one("""
    <table>
        <tr><th>Group</th><th>Item</th></tr>
        <tr><td rowspan="2">Fruit</td><td>Apple</td></tr>
        <tr><td>Pear</td></tr>
        <tr><td>Veg</td><td>Leek</td></tr>
    </table>""")
    assert table.rows == [["Fruit", "Apple"], ["Fruit", "Pear"], ["Veg", "Leek"]]

def test_rowspan_in_the_last_column_and_in_the_middle():
    table = one("""
    <table>
        <tr><th>A</th><th>B</th><th>C</th></tr>
        <tr><td>1</td><td rowspan="2">mid</td><td rowspan="2">end</td></tr>
        <tr><td>2</td></tr>
    </table>""")
    assert table.rows == [["1", "mid", "end"], ["2", "mid", "end"]]

def test_colspan_and_rowspan_together():
    table = one("""
    <table>
        <tr><th>A</th><th>B</th><th>C</th></tr>
        <tr><td colspan="2" rowspan="2">big</td><td>1</td></tr>
        <tr><td>2</td></tr>
        <tr><td>x</td><td>y</td><td>z</td></tr>
    </table>""")
    assert table.rows == [["big", "big", "1"], ["big", "big", "2"], ["x", "y", "z"]]

def test_whole_row_colspan_stretches_to_the_table_width():
    table = one("""
    <table>
        <tr><th>A</th><th>B</th><th>C</th></tr>
        <tr><td colspan="1000">Section one</td></tr>
        <tr><td>1</td><td>2</td><td>3</td></tr>
    </table>""")
    assert table.headers == ["A", "B", "C"]             # not 1000 columns
    assert table.rows[0] == ["Section one"] * 3

def test_overlapping_merged_cells_in_broken_html_do_not_corrupt_later_rows():
    # Row 2: C starts in column 1 and its colspan runs into the square that B (rowspan 3)
    # already occupies. The newer cell wins that square, but B must still stop covering
    # rows once its 3 rows are used up, so row 4 is untouched.
    table = one("""
    <table>
        <tr><th>H1</th><th>H2</th></tr>
        <tr><td>A</td><td rowspan="3">B</td></tr>
        <tr><td colspan="2">C</td></tr>
        <tr><td>D</td></tr>
        <tr><td>E</td><td>F</td></tr>
    </table>""")
    assert table.rows == [["A", "B"], ["C", "C"], ["D", "B"], ["E", "F"]]

def test_a_cell_next_to_a_rowspan_is_placed_in_the_next_free_square():
    table = one("""
    <table>
        <tr><th>H1</th><th>H2</th></tr>
        <tr><td rowspan="2">A</td><td>B</td></tr>
        <tr><td>C</td></tr>
        <tr><td>D</td><td>E</td></tr>
    </table>""")
    assert table.rows == [["A", "B"], ["A", "C"], ["D", "E"]]

def test_odd_span_values_behave_like_a_browser():
    # "abc", "0" and "-3" are invalid, so they count as 1; "2px" is read as 2.
    table = one("""
    <table>
        <tr><th colspan="abc">A</th><th colspan="0">B</th></tr>
        <tr><td colspan="2px">1</td><td rowspan="-3">2</td></tr>
        <tr><td>3</td><td>4</td></tr>
    </table>""")
    assert table.headers == ["A", "B", "Column 3"]
    assert table.rows == [["1", "1", "2"], ["3", "4", ""]]

#headers
def test_header_row_of_th_cells():
    table = one("<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></table>")
    assert table.headers == ["A", "B"]
    assert table.n_rows == 2

def test_multi_row_header_with_colspan_is_merged_into_one_name_per_column():
    table = one("""
    <table>
        <thead>
            <tr><th rowspan="2">Country</th><th colspan="2">Population</th></tr>
            <tr><th>2010</th><th>2020</th></tr>
        </thead>
        <tbody>
            <tr><td>Aland</td><td>10</td><td>12</td></tr>
            <tr><td>Borduria</td><td>20</td><td>25</td></tr>
        </tbody>
    </table>""")
    assert table.headers == ["Country", "Population 2010", "Population 2020"]   # 'Country' not repeated
    assert table.rows == [["Aland", "10", "12"], ["Borduria", "20", "25"]]

def test_thead_is_trusted_even_when_it_uses_td_cells_and_numbers():
    table = one("""
    <table>
        <thead><tr><td>2019</td><td>2020</td></tr></thead>
        <tbody><tr><td>5</td><td>7</td></tr><tr><td>6</td><td>8</td></tr></tbody>
    </table>""")
    assert table.headers == ["2019", "2020"]            # without <thead>, numbers would look like data
    assert table.rows == [["5", "7"], ["6", "8"]]

def test_row_headers_in_the_first_column_do_not_make_the_body_a_header():
    table = one("""
    <table>
        <tr><th>Year</th><th>Sales</th></tr>
        <tr><th>2019</th><td>5</td></tr>
        <tr><th>2020</th><td>7</td></tr>
    </table>""")
    assert table.headers == ["Year", "Sales"]
    assert table.rows == [["2019", "5"], ["2020", "7"]]

def test_a_th_row_is_a_header_even_when_the_names_are_numbers():
    table = one("""
    <table>
        <tr><th></th><th>2019</th><th>2020</th></tr>
        <tr><th>Sales</th><td>5</td><td>7</td></tr>
        <tr><th>Costs</th><td>3</td><td>4</td></tr>
    </table>""")
    assert table.headers == ["Column 1", "2019", "2020"]     # the empty corner cell gets a number
    assert table.rows == [["Sales", "5", "7"], ["Costs", "3", "4"]]

def test_table_of_only_th_cells_still_has_data():
    table = one("<table><tr><th>A</th><th>B</th></tr><tr><th>1</th><th>2</th></tr><tr><th>3</th><th>4</th></tr></table>")
    assert table.headers == ["A", "B"]
    assert table.n_rows == 2

def test_first_row_used_as_header_when_it_looks_like_names():
    table = one("<table><tr><td>Name</td><td>City</td></tr><tr><td>Ann</td><td>Oslo</td></tr><tr><td>Bo</td><td>Rome</td></tr></table>")
    assert table.headers == ["Name", "City"]
    assert table.n_rows == 2
    assert not any("No header" in w for w in table.warnings)

def test_numbered_columns_when_the_first_row_is_data():
    table = one("<table><tr><td>Ann</td><td>42</td></tr><tr><td>Bo</td><td>7</td></tr></table>")
    assert table.headers == ["Column 1", "Column 2"]
    assert table.n_rows == 2                            # the first row is kept as data
    assert any("No header" in w for w in table.warnings)

def test_footnote_markers_are_removed_from_header_names_only():
    table = one("""
    <table>
        <tr><th>Rank [a]</th><th>Population<sup>[1]</sup></th><th>Year [2020]</th></tr>
        <tr><td>1 [b]</td><td>10[2]</td><td>2020</td></tr>
        <tr><td>2</td><td>8</td><td>2021</td></tr>
    </table>""")
    assert table.headers == ["Rank", "Population", "Year [2020]"] # a year in brackets is not a footnote
    assert table.rows[0] == ["1 [b]", "10[2]", "2020"] # cell values are left for the cleaner

def test_empty_and_duplicate_headers_get_usable_names():
    table = one("""
    <table>
        <tr><th>Name</th><th></th><th>Name</th><th>Name</th></tr>
        <tr><td>a</td><td>b</td><td>c</td><td>d</td></tr>
        <tr><td>e</td><td>f</td><td>g</td><td>h</td></tr>
    </table>""")
    assert table.headers == ["Name", "Column 2", "Name (2)", "Name (3)"]

#tidying stuff
def test_short_rows_are_padded_not_dropped():
    table = one("""
    <table>
        <tr><th>A</th><th>B</th><th>C</th></tr>
        <tr><td>1</td><td>2</td><td>3</td></tr>
        <tr><td>4</td><td>5</td></tr>
    </table>""")
    assert table.rows == [["1", "2", "3"], ["4", "5", ""]]
    assert any("fewer cells" in w for w in table.warnings)

def test_long_rows_make_extra_numbered_columns():
    table = one("""
    <table>
        <tr><th>A</th><th>B</th></tr>
        <tr><td>1</td><td>2</td><td>extra</td></tr>
        <tr><td>3</td><td>4</td></tr>
    </table>""")
    assert table.headers == ["A", "B", "Column 3"]
    assert table.rows == [["1", "2", "extra"], ["3", "4", ""]]

def test_blank_rows_and_unnamed_empty_columns_are_removed():
    table = one("""
    <table>
        <tr><th>A</th><th></th><th>B</th></tr>
        <tr><td>1</td><td></td><td>2</td></tr>
        <tr><td></td><td></td><td></td></tr>
        <tr><td>3</td><td></td><td>4</td></tr>
        </table>""")
    assert table.headers == ["A", "B"]
    assert table.rows == [["1", "2"], ["3", "4"]]
    assert any("empty column" in w for w in table.warnings)

def test_a_named_column_with_no_data_is_kept():
    table = one("<table><tr><th>A</th><th>Notes</th></tr><tr><td>1</td><td></td></tr><tr><td>2</td><td></td></tr></table>")
    assert table.headers == ["A", "Notes"]

def test_table_with_no_text_is_skipped():
    assert parse_tables("<table><tr><td></td><td> </td></tr></table><table></table>") == []

#naming
BODY = "<tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr>"

def test_name_from_caption_beats_heading():
    table = one(f"<h2>Heading</h2><table><caption>The  caption</caption>{BODY}</table>")
    assert table.name == "The caption"

def test_name_from_nearest_heading_and_edit_marker_removed():
    table = one(f"<h1>Page title</h1><h3>History[edit]</h3><p>text</p><table>{BODY}</table>")
    assert table.name == "History"

def test_name_from_attributes_then_fallback_number():
    named = one(f'<table aria-label="Quarterly sales">{BODY}</table>')
    from_id = one(f'<table id="population-table">{BODY}</table>')
    ugly_id = one(f'<table id="ctl00_x7">{BODY}</table>')
    assert named.name == "Quarterly sales"
    assert from_id.name == "population table"
    assert ugly_id.name == "Table 1"

def test_fallback_numbers_count_only_tables_that_were_kept():
    html = f"<table></table><table>{BODY}</table><table>{BODY}</table>"
    assert [t.name for t in parse_tables(html)] == ["Table 1", "Table 2"]

def test_duplicate_names_get_numbers():
    html = f"<h2>Stats</h2><table>{BODY}</table><table>{BODY}</table><table>{BODY}</table>"
    assert [t.name for t in parse_tables(html)] == ["Stats", "Stats (2)", "Stats (3)"]

def test_very_long_names_are_shortened():
    table = one(f"<table><caption>{'word ' * 60}</caption>{BODY}</table>")
    assert len(table.name) <= 100 and table.name.endswith("...")

#layout detection
def test_small_tables_are_flagged_as_probable_layout():
    one_column = one("<table><tr><td>menu</td></tr><tr><td>home</td></tr><tr><td>about</td></tr></table>")
    one_row = one("<table><tr><td>a</td><td>b</td><td>c</td></tr></table>")
    assert one_column.is_layout
    assert one_row.is_layout
    assert any("page layout" in w for w in one_row.warnings)

def test_a_normal_table_is_not_layout():
    assert not one(f"<table>{BODY}</table>").is_layout

#encodings

# Polish city names are a good test: in Central European (ISO-8859-2) the letters Ł and ź
# have different byte values than in Western encodings, so a wrong guess shows up at once.
PAGE = "<html><head>{meta}</head><body><table><tr><th>Name</th><th>City</th></tr>" \
    "<tr><td>Ann</td><td>Łódź</td></tr><tr><td>Bo</td><td>Gdańsk</td></tr></table></body></html>"

def test_utf8_page():
    raw = PAGE.format(meta='<meta charset="utf-8">').encode("utf-8")
    assert parse_tables(raw)[0].rows == [["Ann", "Łódź"], ["Bo", "Gdańsk"]]

def test_page_that_declares_its_encoding_in_a_meta_tag():
    raw = PAGE.format(meta='<meta charset="iso-8859-2">').encode("iso-8859-2")
    assert parse_tables(raw)[0].rows == [["Ann", "Łódź"], ["Bo", "Gdańsk"]]

def test_charset_hint_from_the_http_header_is_used():
    raw = PAGE.format(meta="").encode("iso-8859-2") # no meta tag, only the hint knows
    assert parse_tables(raw, encoding="iso-8859-2")[0].rows == [["Ann", "Łódź"], ["Bo", "Gdańsk"]]

def test_charset_from_content_type():
    assert charset_from_content_type("text/html; charset=UTF-8") == "UTF-8"
    assert charset_from_content_type('text/html; charset="iso-8859-1"') == "iso-8859-1"
    assert charset_from_content_type("text/html") is None
    assert charset_from_content_type("") is None
    assert charset_from_content_type("text/html; charset=not-a-real-charset") is None

def test_parse_page_uses_the_pages_url_and_charset():
    raw = PAGE.format(meta="").encode("iso-8859-2")
    page = FetchedPage(url="http://x.test/cities", content=raw, content_type="text/html; charset=ISO-8859-2")
    table = parse_page(page)[0]
    assert table.source_url == "http://x.test/cities"
    assert table.rows[0] == ["Ann", "Łódź"]

#safety
def test_huge_colspan_does_not_create_a_gigantic_table():
    cells = "".join("<td colspan='30'>x</td>" for _ in range(40))      # 1200 columns if taken literally
    table = one(f"<table><tr><th>A</th><th>B</th></tr><tr>{cells}</tr><tr><td>1</td><td>2</td></tr></table>")
    assert table.n_cols <= 200
    assert any("first 200 columns" in w for w in table.warnings)


@pytest.mark.parametrize("junk", ["", " ", "<", "<table", "<table><tr><td>", "\x00\x01", "<table><tr><td colspan='99999999999999999999'>x"])
def test_garbage_input_never_crashes(junk):
    parse_tables(junk)
    parse_tables(junk.encode("utf-8"))