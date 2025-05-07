# Test 5: function returning an object, then read its fields
class Point:
    x: int
    y: int

def add_point(a: Point, b: Point) -> Point:
    return Point(a.x + b.x, a.y + b.y)

p1 = Point(1, 2)
p2 = Point(3, 4)
p3 = add_point(p1, p2)
print(p3.x) # expect 4
print(p3.y) # expect 6
