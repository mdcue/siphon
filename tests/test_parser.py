"""Tests for siphon_app/core/parser.py: turning HTML into tables."""
from pathlib import Path

import pytest

import time

from siphon_app.core.fetcher import FetchedPage, FetchError
from siphon_app.core.parser import MAX_NESTING, charset_from_content_type, parse_page, parse_tables

FIXTURES = Path(__file__).parent / "fixtures"

def one(html: str):
    """Parse html that contains exactly one table and return it."""
    tables = parse_tables(html)
    assert len(tables) == 1
    return tables[0]

# the sample page that broke the old scraper
# the sample page keeps all 5 rows and gets its name from the heading
def test_prices_page_keeps_every_row():
    tables = parse_tables((FIXTURES / "prices.html").read_bytes(), source_url="http://x.test/p")
    assert len(tables) == 1
    table = tables[0]
    assert table.name == "Prices"                       # from the <h2> above it
    assert table.headers == ["Name", "Price", "Cap", "Change"]
    assert table.n_rows == 5                            # the old scraper kept only 4
    assert table.source_url == "http://x.test/p"
    assert not table.is_layout

# a merged cell is copied into each column it spans, with a warning
def test_merged_cell_is_copied_into_each_column_it_covers():
    table = parse_tables((FIXTURES / "prices.html").read_bytes())[0]
    assert table.rows[3] == ["Merged cell row", "Merged cell row", "$1", "5%"]
    assert any("merged" in warning for warning in table.warnings)

# reading the HTML correctly
# HTML with missing closing tags still parses
def test_omitted_end_tags():
    table = one("<table><tr><th>H1<th>H2<tr><td>a<td>b<tr><td>c<td>d</table>")
    assert table.headers == ["H1", "H2"]
    assert table.rows == [["a", "b"], ["c", "d"]]

# a page with no table gives an empty list
def test_no_tables_gives_empty_list():
    assert parse_tables("<html><body><p>nothing here</p></body></html>") == []

# str and bytes input give the same rows
def test_text_input_works_as_well_as_bytes():
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></table>"
    assert parse_tables(html)[0].rows == parse_tables(html.encode("utf-8"))[0].rows

# a table inside a table stays separate from the outer one
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
    assert outer.n_rows == 1                            # only its own row, not the inner table's 3 rows
    assert outer.rows[0][0] == "Left"
    assert inner.headers == ["X", "Y"]
    assert inner.rows == [["1", "2"], ["3", "4"]]       # exactly the inner rows, nothing from the outer
    assert not inner.is_layout

# cell text is cleaned: line breaks, links, spaces, scripts
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

# invisible zero-width spaces are stripped
def test_zero_width_spaces_are_removed():
    table = one("<table><tr><th>A</th><th>B</th></tr><tr><td>a\u200bb</td><td>1</td></tr><tr><td>2</td><td>3</td></tr></table>")
    assert table.rows[0] == ["ab", "1"]

# money amounts in the first row mean it is data, not a header
def test_currency_signs_count_as_numbers_when_guessing_headers():
    # A first row made only of money amounts is data, so the columns get numbered.
    table = one("<table><tr><td>\u20ac5</td><td>\u00a37</td><td>\u00a52</td><td>\u20b99</td></tr><tr><td>1</td><td>2</td><td>3</td><td>4</td></tr></table>")
    assert table.headers == ["Column 1", "Column 2", "Column 3", "Column 4"]
    assert table.n_rows == 2

# a real minus sign counts as a number too
def test_the_unicode_minus_counts_as_a_number_when_guessing_headers():
    table = one("<table><tr><td>\u22123</td><td>\u22124</td></tr><tr><td>1</td><td>2</td></tr></table>")
    assert table.headers == ["Column 1", "Column 2"]
    assert table.n_rows == 2

# tags inside a noscript block are dropped without trouble
def test_tags_nested_inside_a_removed_noscript_are_fine():
    table = one("""
    <table>
    <tr><th>A</th><th>B</th></tr>
    <tr><td><noscript><div>Turn on <p>JavaScript</p><br></div></noscript>ok</td><td>1</td></tr>
    <tr><td>2</td><td>3</td></tr>
    </table>""")
    assert table.rows[0] == ["ok", "1"]

# merged cells (rowspan and colspan)
# a rowspan cell is copied into the rows below
def test_rowspan_is_copied_down():
    table = one("""
    <table>
    <tr><th>Group</th><th>Item</th></tr>
    <tr><td rowspan="2">Fruit</td><td>Apple</td></tr>
    <tr><td>Pear</td></tr>
    <tr><td>Veg</td><td>Leek</td></tr>
    </table>""")
    assert table.rows == [["Fruit", "Apple"], ["Fruit", "Pear"], ["Veg", "Leek"]]

# rowspan works in the last and middle columns
def test_rowspan_in_the_last_column_and_in_the_middle():
    table = one("""
    <table>
    <tr><th>A</th><th>B</th><th>C</th></tr>
    <tr><td>1</td><td rowspan="2">mid</td><td rowspan="2">end</td></tr>
    <tr><td>2</td></tr>
    </table>""")
    assert table.rows == [["1", "mid", "end"], ["2", "mid", "end"]]

# colspan and rowspan on the same cell
def test_colspan_and_rowspan_together():
    table = one("""
    <table>
    <tr><th>A</th><th>B</th><th>C</th></tr>
    <tr><td colspan="2" rowspan="2">big</td><td>1</td></tr>
    <tr><td>2</td></tr>
    <tr><td>x</td><td>y</td><td>z</td></tr>
    </table>""")
    assert table.rows == [["big", "big", "1"], ["big", "big", "2"], ["x", "y", "z"]]

# a full-width colspan fills the whole row
def test_whole_row_colspan_stretches_to_the_table_width():
    table = one("""
    <table>
    <tr><th>A</th><th>B</th><th>C</th></tr>
    <tr><td colspan="1000">Section one</td></tr>
    <tr><td>1</td><td>2</td><td>3</td></tr>
    </table>""")
    assert table.headers == ["A", "B", "C"]             # not 1000 columns
    assert table.rows[0] == ["Section one"] * 3

# overlapping merges in broken HTML don't spoil later rows
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

# a cell beside a rowspan goes in the next free spot
def test_a_cell_next_to_a_rowspan_is_placed_in_the_next_free_square():
    table = one("""
    <table>
    <tr><th>H1</th><th>H2</th></tr>
    <tr><td rowspan="2">A</td><td>B</td></tr>
    <tr><td>C</td></tr>
    <tr><td>D</td><td>E</td></tr>
    </table>""")
    assert table.rows == [["A", "B"], ["A", "C"], ["D", "E"]]

# strange span values are read the way a browser would
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

# headers
# a row of th cells is the header
def test_header_row_of_th_cells():
    table = one("<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></table>")
    assert table.headers == ["A", "B"]
    assert table.n_rows == 2

# a two-level header is joined into one name per column
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

# a thead is the header even with td cells or numbers
def test_thead_is_trusted_even_when_it_uses_td_cells_and_numbers():
    table = one("""
    <table>
    <thead><tr><td>2019</td><td>2020</td></tr></thead>
    <tbody><tr><td>5</td><td>7</td></tr><tr><td>6</td><td>8</td></tr></tbody>
    </table>""")
    assert table.headers == ["2019", "2020"]            # without <thead>, numbers would look like data
    assert table.rows == [["5", "7"], ["6", "8"]]

# th cells down the first column are not a header row
def test_row_headers_in_the_first_column_do_not_make_the_body_a_header():
    table = one("""
    <table>
    <tr><th>Year</th><th>Sales</th></tr>
    <tr><th>2019</th><td>5</td></tr>
    <tr><th>2020</th><td>7</td></tr>
    </table>""")
    assert table.headers == ["Year", "Sales"]
    assert table.rows == [["2019", "5"], ["2020", "7"]]

# a th row is a header even if the names are numbers
def test_a_th_row_is_a_header_even_when_the_names_are_numbers():
    table = one("""
    <table>
    <tr><th></th><th>2019</th><th>2020</th></tr>
    <tr><th>Sales</th><td>5</td><td>7</td></tr>
    <tr><th>Costs</th><td>3</td><td>4</td></tr>
    </table>""")
    assert table.headers == ["Column 1", "2019", "2020"]     # the empty corner cell gets a number
    assert table.rows == [["Sales", "5", "7"], ["Costs", "3", "4"]]

# a table of only th cells still keeps its data
def test_table_of_only_th_cells_still_has_data():
    table = one("<table><tr><th>A</th><th>B</th></tr><tr><th>1</th><th>2</th></tr><tr><th>3</th><th>4</th></tr></table>")
    assert table.headers == ["A", "B"]
    assert table.n_rows == 2

# a first row of words is used as the header
def test_first_row_used_as_header_when_it_looks_like_names():
    table = one("<table><tr><td>Name</td><td>City</td></tr><tr><td>Ann</td><td>Oslo</td></tr><tr><td>Bo</td><td>Rome</td></tr></table>")
    assert table.headers == ["Name", "City"]
    assert table.n_rows == 2
    assert not any("No header" in w for w in table.warnings)

# a first row of numbers is data, so columns are numbered
def test_numbered_columns_when_the_first_row_is_data():
    table = one("<table><tr><td>Ann</td><td>42</td></tr><tr><td>Bo</td><td>7</td></tr></table>")
    assert table.headers == ["Column 1", "Column 2"]
    assert table.n_rows == 2                            # the first row is kept as data
    assert any("No header" in w for w in table.warnings)

# footnote marks like [1] are stripped from headers only
def test_footnote_markers_are_removed_from_header_names_only():
    table = one("""
    <table>
    <tr><th>Rank [a]</th><th>Population<sup>[1]</sup></th><th>Year [2020]</th></tr>
    <tr><td>1 [b]</td><td>10[2]</td><td>2020</td></tr>
    <tr><td>2</td><td>8</td><td>2021</td></tr>
    </table>""")
    assert table.headers == ["Rank", "Population", "Year [2020]"]   # a year in brackets is not a footnote
    assert table.rows[0] == ["1 [b]", "10[2]", "2020"]              # cell values are left for the cleaner

# blank and repeated header names are made usable
def test_empty_and_duplicate_headers_get_usable_names():
    table = one("""
    <table>
    <tr><th>Name</th><th></th><th>Name</th><th>Name</th></tr>
    <tr><td>a</td><td>b</td><td>c</td><td>d</td></tr>
    <tr><td>e</td><td>f</td><td>g</td><td>h</td></tr>
    </table>""")
    assert table.headers == ["Name", "Column 2", "Name (2)", "Name (3)"]

# ragged rows and empty things
# short rows are padded with blanks
def test_short_rows_are_padded_not_dropped():
    table = one("""
    <table>
    <tr><th>A</th><th>B</th><th>C</th></tr>
    <tr><td>1</td><td>2</td><td>3</td></tr>
    <tr><td>4</td><td>5</td></tr>
    </table>""")
    assert table.rows == [["1", "2", "3"], ["4", "5", ""]]
    assert any("fewer cells" in w for w in table.warnings)

# extra cells in a long row get numbered columns
def test_long_rows_make_extra_numbered_columns():
    table = one("""
    <table>
    <tr><th>A</th><th>B</th></tr>
    <tr><td>1</td><td>2</td><td>extra</td></tr>
    <tr><td>3</td><td>4</td></tr>
    </table>""")
    assert table.headers == ["A", "B", "Column 3"]
    assert table.rows == [["1", "2", "extra"], ["3", "4", ""]]

# fully blank rows and unnamed empty columns are removed
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

# an empty column that has a name is kept
def test_a_named_column_with_no_data_is_kept():
    table = one("<table><tr><th>A</th><th>Notes</th></tr><tr><td>1</td><td></td></tr><tr><td>2</td><td></td></tr></table>")
    assert table.headers == ["A", "Notes"]

# a table with no text at all is skipped
def test_table_with_no_text_is_skipped():
    assert parse_tables("<table><tr><td></td><td> </td></tr></table><table></table>") == []

# naming tables
# a small set of rows the naming tests wrap in different headings
BODY = "<tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr>"

# a caption wins over a heading
def test_name_from_caption_beats_heading():
    table = one(f"<h2>Heading</h2><table><caption>The  caption</caption>{BODY}</table>")
    assert table.name == "The caption"

# the nearest heading is used, minus the [edit] marker
def test_name_from_nearest_heading_and_edit_marker_removed():
    table = one(f"<h1>Page title</h1><h3>History[edit]</h3><p>text</p><table>{BODY}</table>")
    assert table.name == "History"

# then aria-label or a readable id, and finally 'Table 1'
def test_name_from_attributes_then_fallback_number():
    named = one(f'<table aria-label="Quarterly sales">{BODY}</table>')
    from_id = one(f'<table id="population-table">{BODY}</table>')
    ugly_id = one(f'<table id="ctl00_x7">{BODY}</table>')
    assert named.name == "Quarterly sales"
    assert from_id.name == "population table"
    assert ugly_id.name == "Table 1"

# Table N counts only the tables that were kept
def test_fallback_numbers_count_only_tables_that_were_kept():
    html = f"<table></table><table>{BODY}</table><table>{BODY}</table>"
    assert [t.name for t in parse_tables(html)] == ["Table 1", "Table 2"]

# repeated names get (2), (3)
def test_duplicate_names_get_numbers():
    html = f"<h2>Stats</h2><table>{BODY}</table><table>{BODY}</table><table>{BODY}</table>"
    assert [t.name for t in parse_tables(html)] == ["Stats", "Stats (2)", "Stats (3)"]

# very long names are cut to 100 characters with ...
def test_very_long_names_are_shortened():
    table = one(f"<table><caption>{'word ' * 60}</caption>{BODY}</table>")
    assert len(table.name) <= 100 and table.name.endswith("...")

# layout tables
# one-row or one-column tables are probably page layout
def test_small_tables_are_flagged_as_probable_layout():
    one_column = one("<table><tr><td>menu</td></tr><tr><td>home</td></tr><tr><td>about</td></tr></table>")
    one_row = one("<table><tr><td>a</td><td>b</td><td>c</td></tr></table>")
    assert one_column.is_layout
    assert one_row.is_layout
    assert any("page layout" in w for w in one_row.warnings)

# a normal table is not flagged
def test_a_normal_table_is_not_layout():
    assert not one(f"<table>{BODY}</table>").is_layout

# text encodings

# Polish city names make a good test: Ł and ź have different bytes in ISO-8859-2 than in
# Western encodings, so a wrong guess shows up at once.
PAGE = "<html><head>{meta}</head><body><table><tr><th>Name</th><th>City</th></tr>" \
    "<tr><td>Ann</td><td>Łódź</td></tr><tr><td>Bo</td><td>Gdańsk</td></tr></table></body></html>"

# a UTF-8 page reads correctly
def test_utf8_page():
    raw = PAGE.format(meta='<meta charset="utf-8">').encode("utf-8")
    assert parse_tables(raw)[0].rows == [["Ann", "Łódź"], ["Bo", "Gdańsk"]]

# the encoding in a meta tag is respected
def test_page_that_declares_its_encoding_in_a_meta_tag():
    raw = PAGE.format(meta='<meta charset="iso-8859-2">').encode("iso-8859-2")
    assert parse_tables(raw)[0].rows == [["Ann", "Łódź"], ["Bo", "Gdańsk"]]

# with no meta tag, the encoding hint passed in is used
def test_charset_hint_from_the_http_header_is_used():
    raw = PAGE.format(meta="").encode("iso-8859-2")            # no meta tag: only the hint knows
    assert parse_tables(raw, encoding="iso-8859-2")[0].rows == [["Ann", "Łódź"], ["Bo", "Gdańsk"]]

# pulls the charset out of a Content-Type header, or None
def test_charset_from_content_type():
    assert charset_from_content_type("text/html; charset=UTF-8") == "UTF-8"
    assert charset_from_content_type('text/html; charset="iso-8859-1"') == "iso-8859-1"
    assert charset_from_content_type("text/html") is None
    assert charset_from_content_type("") is None
    assert charset_from_content_type("text/html; charset=not-a-real-charset") is None

# parse_page takes the url and charset from the fetched page
def test_parse_page_uses_the_pages_url_and_charset():
    raw = PAGE.format(meta="").encode("iso-8859-2")
    page = FetchedPage(url="http://x.test/cities", content=raw, content_type="text/html; charset=ISO-8859-2")
    table = parse_page(page)[0]
    assert table.source_url == "http://x.test/cities"
    assert table.rows[0] == ["Ann", "Łódź"]

# bad input
# a huge colspan can't blow the table up past 200 columns
def test_huge_colspan_does_not_create_a_gigantic_table():
    cells = "".join("<td colspan='30'>x</td>" for _ in range(40))      # 1200 columns if taken literally
    table = one(f"<table><tr><th>A</th><th>B</th></tr><tr>{cells}</tr><tr><td>1</td><td>2</td></tr></table>")
    assert table.n_cols <= 200
    assert any("first 200 columns" in w for w in table.warnings)

# junk input never crashes
@pytest.mark.parametrize("junk", ["", " ", "<", "<table", "<table><tr><td>", "\x00\x01", "<table><tr><td colspan='99999999999999999999'>x"])
def test_garbage_input_never_crashes(junk):
    parse_tables(junk)
    parse_tables(junk.encode("utf-8"))

# hostile and huge pages: they must be refused or read quickly, never hang the app
def timed(html):
    started = time.perf_counter()
    result = parse_tables(html)
    return result, time.perf_counter() - started

# a page nested far deeper than any real page is refused up front, with a worded message
def test_a_page_nested_absurdly_deep_is_refused():
    depth = MAX_NESTING + 1
    html = "<table><tr><td>" + "<div>" * depth + "x" + "</div>" * depth + "</td></tr></table>"
    started = time.perf_counter()
    with pytest.raises(FetchError, match="levels deep"):
        parse_tables(html)
    assert time.perf_counter() - started < 2

# a deep but believable page still works
def test_ordinary_deep_nesting_is_fine():
    depth = 200
    cell = "<div>" * depth + "deep" + "</div>" * depth
    table = one(f"<table><tr><th>A</th><th>B</th></tr><tr><td>{cell}</td><td>x</td></tr></table>")
    assert table.rows[0] == ["deep", "x"]

# a long page full of side-by-side (properly closed) divs is not deep: the count goes back down
def test_many_closed_siblings_do_not_count_as_nesting():
    html = "<div>a</div>" * (MAX_NESTING * 3) + "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    assert one(html).rows == [["1", "2"]]

# old pages that never close <p>, <li> or <td> are not "deep", however many there are
def test_pages_with_many_unclosed_tags_are_not_mistaken_for_deep_nesting():
    html = "<p>x" * 3000 + "<li>y" * 3000 + "<table><tr><th>A<th>B<tr><td>1<td>2</table>"
    tables, seconds = timed(html)
    assert tables[0].rows == [["1", "2"]]
    assert seconds < 5

# many of one tag side by side used to take minutes, because every one re-scanned its siblings
@pytest.mark.parametrize("piece, where", [
    ("a<br>", "cell"), ("<p>a</p>", "cell"), ("<script>x</script>", "page"), ("<tr><td>a<td>b", "table"),
])
def test_thousands_of_repeated_tags_are_read_quickly(piece, where):
    count = 20000
    if where == "cell":
        html = "<table><tr><th>A</th><th>B</th></tr><tr><td>" + piece * count + "</td><td>x</td></tr></table>"
    elif where == "page":
        html = piece * count + "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    else:
        html = "<table><tr><th>A<th>B" + piece * count + "</table>"
    tables, seconds = timed(html)
    assert tables
    assert seconds < 5

# spacing around block tags and <br> is added while reading, and the page is left alone otherwise
@pytest.mark.parametrize("cell, expected", [
    ("Hello<p>World</p>again", "Hello World again"),
    ("one<br>two", "one two"),
    ("<b>Hel</b>lo", "Hello"),                                    # inline tags don't add a space
    ("a<div><div>b</div></div>c", "a b c"),
    ("x<script>alert(1)</script>y", "xy"),
    ("x<!-- note -->y", "xy"),                                    # comments are not text
    ("<ul><li>one</li><li>two</li></ul>", "one two"),
])
def test_text_is_spaced_around_blocks_and_breaks(cell, expected):
    table = one(f"<table><tr><th>A</th><th>B</th></tr><tr><td>{cell}</td><td>z</td></tr></table>")
    assert table.rows[0][0] == expected