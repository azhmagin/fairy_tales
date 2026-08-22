from storybook.content import STYLES, load_plots


def test_plots_load_and_have_12_scenes():
    plots = load_plots()
    assert len(plots) >= 5
    for p in plots.values():
        assert p.pages == 12
        assert [s["n"] for s in p.scenes] == list(range(1, 13))
        assert "{name}" in p.title
        assert p.hero_outfit
        assert p.scenes[-1]["beat"] in ("домой", "сон")  # calm ending


def test_style_prompt_forbids_text():
    assert "no text" in STYLES["soft3d"]
