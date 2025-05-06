# Test 6: inline constructed dataclasses inside expressions

class Rect:
    len: int
    width: int

def perimeter(r: Rect) -> int:
    return 2 * (r.len + r.width)

print(perimeter(Rect(3, 5))) # expect 16