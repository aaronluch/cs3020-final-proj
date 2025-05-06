# Test 7: constructor helper + chaining into another function
class Rect:
    len: int
    width: int

def make_rect(l: int, w: int) -> Rect:
    return Rect(l, w)

def perimeter(r: Rect) -> int:
    return 2 * (r.len + r.width)

print(perimeter(make_rect(7, 3))) # expect 20