% Stage 1: three independent summaries of the same immutable input.
% Stage 2: two calculations consuming Stage 1 results.
% Stage 3: two calculations consuming Stage 2 results.
tempo 6000
C4 = sum(data) -> total
E4 = count(data) -> n
G4 = maximum(data) -> high
A4 = divide(total, n) -> average
B4 = divide(high, n) -> normalized_max
D5 = multiply(average, n) -> reconstructed_total
F5 = add(average, normalized_max) -> adjusted_average

[C4 E4 G4] [A4 B4] [D5 F5]
