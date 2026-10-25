% A runtime failure in the second stage prevents publication of both peers.
% The first-stage outputs remain available in the run's result report.
tempo 6000
C4 = sum(data) -> total
E4 = subtract(total, total) -> zero
G4 = divide(total, zero) -> impossible
A4 = multiply(total, total) -> peer
B4 = add(peer, total) -> later
C4 E4 [G4 A4] B4
