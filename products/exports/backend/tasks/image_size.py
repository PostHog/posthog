from PIL import Image, ImageOps


def fit_image_to_size(path: str, width: int | None, height: int | None) -> None:
    if width is None and height is None:
        return
    if width is not None and not 320 <= width <= 4000:
        raise ValueError("Invalid image width")
    if height is not None and not 200 <= height <= 5000:
        raise ValueError("Invalid image height")
    with Image.open(path) as image:
        if width is None:
            assert height is not None
            width = max(1, min(4000, round(image.width * height / image.height)))
        if height is None:
            height = max(1, min(5000, round(image.height * width / image.width)))
        fitted = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
        output = Image.new("RGBA", (width, height), image.crop((0, 0, 1, 1)).convert("RGBA").getpixel((0, 0)))
        output.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
        output.save(path, format="PNG")
