% Same note arrangement; wrong arithmetic assignment. It still compiles.
% A correct-looking musical structure cannot establish the intended answer.
tempo 6000
C4 = sum(data) -> total
E4 = count(data) -> n
G4 = maximum(data) -> high
A4 = subtract(total, n) -> average
B4 = divide(high, n) -> normalized_max
D5 = multiply(average, n) -> reconstructed_total
F5 = add(average, normalized_max) -> adjusted_average
[C4 E4 G4] [A4 B4] [D5 F5]
