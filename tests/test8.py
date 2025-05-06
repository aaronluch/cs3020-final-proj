# Test 8: more complex arithmetic on a single object
class Data:
    a: int
    b: int
    c: int

def f(d: Data) -> int:
    return d.a + d.b * d.c

d = Data(2, 3, 4)
print(f(d)) # expect 2 + 3*4 = 14