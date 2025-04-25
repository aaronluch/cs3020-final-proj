class Rectangle:
    len: int
    width: int
    
def perimeter(rectangle: Rectangle) -> int:
    return 2 * (rectangle.len + rectangle.width)

r = Rectangle()
r.len = 5
r.width = 10

print(perimeter(r))