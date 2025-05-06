# Test 9: mixing two different classes in one call
class P:
    x: int
    y: int

class R:
    len: int
    width: int

def combine(p: P, r: R) -> int:
    return p.x * r.len + p.y * r.width

p = P(1, 2)
r = R(3, 4)
print(combine(p, r)) # expect 1*3 + 2*4 = 11