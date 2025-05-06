# Test 4: simple constructor function + inline reads
class Point:
    x: int
    y: int

def mid_x(a: Point, b: Point) -> int:
    return a.x + b.x

p1 = Point(10, 20)
p2 = Point(30, 40)
print(mid_x(p1, p2)) # expect 40