from pathlib import Path

import pytest

from PIL import Image

from products.exports.backend.tasks.image_size import fit_image_to_size


@pytest.mark.parametrize(
    "width,height,expected",
    [(None, None, (1600, 1200)), (1200, None, (1200, 900)), (None, 300, (400, 300)), (1200, 630, (1200, 630))],
)
def test_image_size_preserves_content(tmp_path: Path, width, height, expected) -> None:
    path = str(tmp_path / "chart.png")
    image = Image.new("RGB", (1600, 1200), "white")
    image.paste("red", (0, 0, 1600, 40))
    image.paste("blue", (0, 1160, 1600, 1200))
    image.save(path)

    fit_image_to_size(path, width, height)

    with Image.open(path) as result:
        assert result.size == expected
        center_x = result.width // 2
        top = result.getpixel((center_x, 0))
        bottom = result.getpixel((center_x, result.height - 1))
        assert isinstance(top, tuple) and top[:3] == (255, 0, 0)
        assert isinstance(bottom, tuple) and bottom[:3] == (0, 0, 255)
