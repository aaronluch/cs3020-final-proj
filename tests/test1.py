# Test 1: simple rectangle perimeter calculation
class Rectangle:
    len: int
    width: int
    
def perimeter(rectangle: Rectangle) -> int:
    return 2 * (rectangle.len + rectangle.width)

r = Rectangle(5, 10)

print(perimeter(r)) # expect 30