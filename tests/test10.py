# Test 10: summing the same field across an array of objects
class Rect:
    len: int
    width: int

def total_length(r1: Rect, r2: Rect, r3: Rect) -> int:
    return r1.len + r2.len + r3.len

a = Rect(1, 5)
b = Rect(2, 6)
c = Rect(3, 7)
print(total_length(a, b, c)) # expect 1+2+3 = 6