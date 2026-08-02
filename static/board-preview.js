/**
 * Aperçu miniature d'une position d'échecs à partir d'un FEN, en pur
 * DOM/CSS (glyphes Unicode ♔♕♖♗♘♙), sans dépendance à chess.js/chessboard.js.
 * Utilisé pour les vignettes des cartes de puzzles (positions non interactives).
 */

const MINI_BOARD_GLYPHS = {
  P: '♙', N: '♘', B: '♗', R: '♖', Q: '♕', K: '♔',
  p: '♟', n: '♞', b: '♝', r: '♜', q: '♛', k: '♚'
};

function miniBoardParseFen(fen) {
  const placement = (fen || '').split(' ')[0] || '';
  return placement.split('/').map(row => {
    const cells = [];
    for (const ch of row) {
      if (/\d/.test(ch)) {
        for (let i = 0; i < parseInt(ch, 10); i++) cells.push(null);
      } else {
        cells.push(ch);
      }
    }
    // Sécurité : une rangée FEN valide fait toujours 8 cases.
    while (cells.length < 8) cells.push(null);
    return cells.slice(0, 8);
  });
}

/** Construit et retourne un élément DOM représentant le mini-échiquier. */
function renderMiniBoard(fen) {
  const board = document.createElement('div');
  board.className = 'mini-board';

  if (!fen) {
    board.classList.add('mini-board-empty');
    return board;
  }

  const rows = miniBoardParseFen(fen);
  rows.forEach((row, r) => {
    row.forEach((cell, c) => {
      const square = document.createElement('div');
      const isLight = (r + c) % 2 === 0;
      square.className = 'mini-square ' + (isLight ? 'mini-light' : 'mini-dark');
      if (cell) {
        square.textContent = MINI_BOARD_GLYPHS[cell] || '';
        square.classList.add(cell === cell.toUpperCase() ? 'mini-white' : 'mini-black');
      }
      board.appendChild(square);
    });
  });

  return board;
}
