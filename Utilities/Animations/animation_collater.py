# Takes a series of 240x160 frames and converts them into one spritesheet
# and an associated indexing file for use by the BattleAnimation routines

import glob
from PIL import Image

COLORKEY = (128, 160, 128)

count = 0
index_lines = []
for fp in sorted(glob.glob('fixed*.png')):
    print(fp)
    count += 1
    name = 'Attack' + str(count) 
    image = Image.open(fp).convert('RGB')

    width, height = image.size

    # Convert colorkey colors to 0, 0, 0
    for x in xrange(width):
        for y in xrange(height):
            color = image.getpixel((x, y))
            if color == COLORKEY:
                image.putpixel((x, y), (0, 0, 0))

    # Now get bbox
    left, upper, right, lower = image.getbbox()
    # x, y on sprite_sheet
    # Width, Height
    width, height = right - left, lower - upper
    # Offset from 0, 0
    offset = left, upper
    # Crop
    cropped = image.crop((left, upper, left+right, upper+lower))

    index_lines.append((cropped, name, width, height, offset))

index_script = open('New-Index.txt', 'w')

total_width = sum(i[2] for i in index_lines)
max_height = max(i[3] for i in index_lines)

sprite_sheet = Image.new('RGB', (total_width, max_height))

x = 0
for image, name, width, height, offset in index_lines:
    print(name)
    sprite_sheet.paste(image, (x, 0))
    index_script.write(name + ';' + str(x) + ',0;' + str(width) + ',' + str(height) + ';' + str(offset[0]) + ',' + str(offset[1]) + '\n')
    x += width

# Now convert 0, 0, 0 back to colorkey
for x in xrange(total_width):
    for y in xrange(max_height):
        color = sprite_sheet.getpixel((x, y))
        if color == (0, 0, 0):
            sprite_sheet.putpixel((x, y), COLORKEY)

sprite_sheet.save('new_spritesheet.png')
index_script.close()