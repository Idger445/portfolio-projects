#include <algorithm>
#include <array>
#include <iostream>
#include <sstream>
#include <string>

class Game {
public:
    enum class Move { accepted, out_of_range, occupied };

    char player() const { return player_; }

    Move play(int cell) {
        if (cell < 1 || cell > static_cast<int>(board_.size())) {
            return Move::out_of_range;
        }

        char& square = board_[cell - 1];
        if (square != ' ') {
            return Move::occupied;
        }

        square = player_;
        player_ = player_ == 'X' ? 'O' : 'X';
        return Move::accepted;
    }

    char winner() const {
        constexpr std::array<std::array<int, 3>, 8> lines{{
            {0, 1, 2}, {3, 4, 5}, {6, 7, 8},
            {0, 3, 6}, {1, 4, 7}, {2, 5, 8},
            {0, 4, 8}, {2, 4, 6},
        }};

        for (const auto& line : lines) {
            const char mark = board_[line[0]];
            if (mark != ' ' && mark == board_[line[1]] && mark == board_[line[2]]) {
                return mark;
            }
        }
        return ' ';
    }

    bool full() const {
        return std::none_of(board_.begin(), board_.end(), [](char mark) { return mark == ' '; });
    }

    void print(std::ostream& output) const {
        output << "\n";
        for (std::size_t index = 0; index < board_.size(); ++index) {
            const char square = board_[index];
            output << ' ' << (square == ' ' ? static_cast<char>('1' + index) : square) << ' ';
            if (index % 3 != 2) {
                output << '|';
            } else if (index + 1 < board_.size()) {
                output << "\n---+---+---\n";
            }
        }
        output << "\n\n";
    }

private:
    std::array<char, 9> board_{' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' '};
    char player_ = 'X';
};

bool read_choice(char& choice) {
    std::string input;
    if (!std::getline(std::cin, input)) {
        return false;
    }

    std::istringstream line(input);
    char extra;
    if (!(line >> choice) || line >> extra) {
        choice = '\0';
    }
    return true;
}

int main() {
    std::cout << "Tic-tac-toe\nTwo players share one keyboard. Enter a square number or q to quit.\n";

    for (;;) {
        Game game;
        game.print(std::cout);

        while (game.winner() == ' ' && !game.full()) {
            std::cout << game.player() << " to move: ";
            char choice;
            if (!read_choice(choice) || choice == 'q' || choice == 'Q') {
                return 0;
            }

            const Game::Move move = game.play(choice - '0');
            if (move == Game::Move::out_of_range) {
                std::cout << "Enter one square number (1-9).\n";
                continue;
            }
            if (move == Game::Move::occupied) {
                std::cout << "That square is already occupied.\n";
                continue;
            }
            game.print(std::cout);
        }

        const char winner = game.winner();
        if (winner != ' ') {
            std::cout << winner << " wins!\n";
        } else {
            std::cout << "Draw.\n";
        }

        for (;;) {
            std::cout << "Play again? [y/n]: ";
            char choice;
            if (!read_choice(choice) || choice == 'n' || choice == 'N' || choice == 'q' || choice == 'Q') {
                return 0;
            }
            if (choice == 'y' || choice == 'Y') {
                break;
            }
            std::cout << "Enter y or n.\n";
        }
    }
}
