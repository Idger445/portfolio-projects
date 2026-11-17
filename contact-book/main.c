#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

#define FILE_HEADER "contact-book-v1"

typedef struct {
    char name[97];
    char phone[49];
    char email[129];
} Contact;

typedef struct {
    Contact *items;
    size_t count;
    size_t capacity;
} Book;

typedef enum { LINE_OK, LINE_END, LINE_INVALID, LINE_ERROR } LineStatus;

/* Read a whole line so an invalid line cannot spill into the next prompt. */
static LineStatus read_line(FILE *stream, char *line, size_t size) {
    size_t length = 0;
    int invalid = 0;
    int byte;
    while ((byte = fgetc(stream)) != EOF && byte != '\n') {
        if (byte == '\0' || length == size - 1) {
            invalid = 1;
        } else {
            line[length++] = (char)byte;
        }
    }
    if (byte == EOF && ferror(stream)) {
        return LINE_ERROR;
    }
    if (byte == EOF && length == 0 && !invalid) {
        return LINE_END;
    }

    if (length > 0 && line[length - 1] == '\r') {
        --length;
    }
    line[length] = '\0';
    return invalid ? LINE_INVALID : LINE_OK;
}

static int valid_field(const char *field, size_t capacity, int allow_empty) {
    if (strlen(field) >= capacity) {
        return 0;
    }

    int has_text = 0;
    for (const unsigned char *byte = (const unsigned char *)field; *byte; ++byte) {
        if (iscntrl(*byte)) {
            return 0;
        }
        if (!isspace(*byte)) {
            has_text = 1;
        }
    }
    return has_text || (allow_empty && *field == '\0');
}

static int append_contact(Book *book, const Contact *contact) {
    if (book->count == book->capacity) {
        if (book->capacity > SIZE_MAX / sizeof(*book->items) / 2) {
            return 0;
        }
        const size_t capacity = book->capacity ? book->capacity * 2 : 8;
        Contact *items = realloc(book->items, capacity * sizeof(*items));
        if (!items) {
            return 0;
        }
        book->items = items;
        book->capacity = capacity;
    }
    book->items[book->count++] = *contact;
    return 1;
}

static int parse_contact(char *line, Contact *contact) {
    char *phone = strchr(line, '\t');
    if (!phone) {
        return 0;
    }
    *phone++ = '\0';

    char *email = strchr(phone, '\t');
    if (!email) {
        return 0;
    }
    *email++ = '\0';

    if (!valid_field(line, sizeof(contact->name), 0) ||
        !valid_field(phone, sizeof(contact->phone), 0) ||
        !valid_field(email, sizeof(contact->email), 1)) {
        return 0;
    }

    strcpy(contact->name, line);
    strcpy(contact->phone, phone);
    strcpy(contact->email, email);
    return 1;
}

static int load_book(Book *book, const char *path) {
    FILE *file = fopen(path, "rb");
    if (!file) {
        if (errno == ENOENT) {
            return 1;
        }
        perror(path);
        return 0;
    }

    // Space for the three fields at full length, two tabs, CR, and the terminator.
    char line[sizeof(Contact) + 1];
    if (read_line(file, line, sizeof(line)) != LINE_OK || strcmp(line, FILE_HEADER) != 0) {
        fprintf(stderr, "%s: missing or invalid file header.\n", path);
        fclose(file);
        return 0;
    }

    LineStatus status;
    size_t number = 1;
    while ((status = read_line(file, line, sizeof(line))) != LINE_END) {
        Contact contact = {0};
        ++number;
        if (status != LINE_OK || !parse_contact(line, &contact)) {
            fprintf(stderr, "%s: cannot read contact on line %zu.\n", path, number);
            fclose(file);
            return 0;
        }
        if (!append_contact(book, &contact)) {
            fputs("Could not allocate contact list.\n", stderr);
            fclose(file);
            return 0;
        }
    }
    return fclose(file) == 0;
}

static int replace_file(const char *temporary, const char *path) {
#ifdef _WIN32
    if (MoveFileExA(temporary, path, MOVEFILE_REPLACE_EXISTING)) {
        return 1;
    }
    fprintf(stderr, "%s: Windows could not replace the file (code %lu).\n",
            path, (unsigned long)GetLastError());
    return 0;
#else
    if (rename(temporary, path) == 0) {
        return 1;
    }
    perror(path);
    return 0;
#endif
}

static char *path_with_suffix(const char *path, const char *suffix) {
    char *result = malloc(strlen(path) + strlen(suffix) + 1);
    if (result) {
        strcpy(result, path);
        strcat(result, suffix);
    } else {
        fputs("Could not allocate file path.\n", stderr);
    }
    return result;
}

static int save_book(const Book *book, const char *path) {
    char *temporary = path_with_suffix(path, ".tmp");
    if (!temporary) {
        return 0;
    }

    FILE *file = fopen(temporary, "wbx");
    if (!file) {
        perror(temporary);
        free(temporary);
        return 0;
    }

    int ok = fputs(FILE_HEADER "\n", file) != EOF;
    for (size_t index = 0; ok && index < book->count; ++index) {
        const Contact *contact = &book->items[index];
        ok = fprintf(file, "%s\t%s\t%s\n", contact->name, contact->phone, contact->email) >= 0;
    }
    if (fclose(file) != 0) {
        ok = 0;
    }

    if (ok) {
        ok = replace_file(temporary, path);
    } else {
        fprintf(stderr, "%s: could not write contacts.\n", temporary);
    }
    if (!ok) {
        remove(temporary);
    }
    free(temporary);
    return ok;
}

static LineStatus prompt(const char *label, char *line, size_t size) {
    fputs(label, stdout);
    fflush(stdout);
    return read_line(stdin, line, size);
}

static int read_field(const char *label, char *field, size_t capacity, int allow_empty) {
    char line[sizeof(((Contact *)0)->email) + 1];
    for (;;) {
        const LineStatus status = prompt(label, line, sizeof(line));
        if (status == LINE_END || status == LINE_ERROR) {
            return 0;
        }
        if (status == LINE_OK && valid_field(line, capacity, allow_empty)) {
            strcpy(field, line);
            return 1;
        }
        printf("Enter a %sfield up to %zu bytes without control characters.\n",
               allow_empty ? "valid " : "non-empty ", capacity - 1);
    }
}

static int read_contact(Contact *contact) {
    return read_field("Name: ", contact->name, sizeof(contact->name), 0) &&
           read_field("Phone: ", contact->phone, sizeof(contact->phone), 0) &&
           read_field("Email (optional): ", contact->email, sizeof(contact->email), 1);
}

static int contains(const char *field, const char *query) {
    for (; *field; ++field) {
        const unsigned char *cursor = (const unsigned char *)field;
        const unsigned char *needle = (const unsigned char *)query;
        while (*needle && *cursor && tolower(*cursor) == tolower(*needle)) {
            ++cursor;
            ++needle;
        }
        if (!*needle) {
            return 1;
        }
    }
    return 0;
}

static void show_contacts(const Book *book, const char *query) {
    size_t matches = 0;
    for (size_t index = 0; index < book->count; ++index) {
        const Contact *contact = &book->items[index];
        if (query && !contains(contact->name, query) && !contains(contact->phone, query) &&
            !contains(contact->email, query)) {
            continue;
        }
        printf("%zu. %s | %s", index + 1, contact->name, contact->phone);
        if (*contact->email) {
            printf(" | %s", contact->email);
        }
        putchar('\n');
        ++matches;
    }
    if (matches == 0) {
        puts(query ? "No matches." : "No contacts yet.");
    }
}

static int read_index(size_t count, size_t *index) {
    char line[32];
    for (;;) {
        const LineStatus status = prompt("Contact number (0 to cancel): ", line, sizeof(line));
        if (status == LINE_END || status == LINE_ERROR) {
            return 0;
        }
        if (status == LINE_OK) {
            char *end;
            errno = 0;
            const unsigned long long number = strtoull(line, &end, 10);
            if (isdigit((unsigned char)line[0]) && *end == '\0' && errno == 0 && number <= count) {
                if (number == 0) {
                    return 0;
                }
                *index = (size_t)number - 1;
                return 1;
            }
        }
        printf("Enter a number from 0 to %zu.\n", count);
    }
}

static int run_book(Book *book, const char *path) {
    puts("Contact book");
    for (;;) {
        puts("\n1 List   2 Add   3 Search   4 Edit   5 Delete   0 Exit");
        char choice[8];
        const LineStatus status = prompt("> ", choice, sizeof(choice));
        if (status == LINE_END) {
            return 1;
        }
        if (status == LINE_ERROR) {
            fputs("Input could not be read.\n", stderr);
            return 0;
        }
        if (status != LINE_OK || strlen(choice) != 1) {
            puts("Choose an option from 0 to 5.");
            continue;
        }

        Contact contact = {0};
        size_t index;
        switch (choice[0]) {
            case '0':
                return 1;
            case '1':
                show_contacts(book, NULL);
                continue;
            case '2':
                if (!read_contact(&contact)) {
                    return !ferror(stdin);
                }
                if (!append_contact(book, &contact)) {
                    fputs("Could not allocate contact list.\n", stderr);
                    return 0;
                }
                break;
            case '3': {
                char query[sizeof(contact.email)];
                if (!read_field("Search: ", query, sizeof(query), 0)) {
                    return !ferror(stdin);
                }
                show_contacts(book, query);
                continue;
            }
            case '4':
            case '5':
                show_contacts(book, NULL);
                if (book->count == 0 || !read_index(book->count, &index)) {
                    continue;
                }
                if (choice[0] == '4') {
                    if (!read_contact(&contact)) {
                        return !ferror(stdin);
                    }
                    book->items[index] = contact;
                } else {
                    --book->count;
                    memmove(&book->items[index], &book->items[index + 1],
                            (book->count - index) * sizeof(*book->items));
                }
                break;
            default:
                puts("Choose an option from 0 to 5.");
                continue;
        }

        if (!save_book(book, path)) {
            return 0;
        }
        puts("Saved.");
    }
}

int main(int argc, char **argv) {
    if (argc > 2 || (argc == 2 && !argv[1][0])) {
        fputs("Usage: contact-book [storage-file]\n", stderr);
        return EXIT_FAILURE;
    }

#ifdef _WIN32
    SetConsoleCP(CP_UTF8);
    SetConsoleOutputCP(CP_UTF8);
#endif

    const char *path = argc == 2 ? argv[1] : "contacts.tsv";
    char *lock_path = path_with_suffix(path, ".lock");
    if (!lock_path) {
        return EXIT_FAILURE;
    }
    FILE *lock = fopen(lock_path, "wbx");
    if (!lock) {
        perror(lock_path);
        free(lock_path);
        return EXIT_FAILURE;
    }

    Book book = {0};
    int ok = load_book(&book, path) && run_book(&book, path);
    free(book.items);
    fclose(lock);
    if (remove(lock_path) != 0) {
        perror(lock_path);
        ok = 0;
    }
    free(lock_path);
    return ok ? EXIT_SUCCESS : EXIT_FAILURE;
}
