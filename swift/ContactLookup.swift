import Foundation
import Contacts

struct ContactResult: Codable {
    let handle: String
    let name: String?
    let givenName: String?
    let familyName: String?
    let nickname: String?
    let initials: String?
    let hasImage: Bool
    let imageBase64: String?
}

func initials(from contact: CNContact) -> String? {
    let first = contact.givenName.first.map { String($0) } ?? ""
    let last = contact.familyName.first.map { String($0) } ?? ""
    let nick = contact.nickname.first.map { String($0) } ?? ""

    if !nick.isEmpty {
        return nick.uppercased()
    }

    let combined = first + last
    return combined.isEmpty ? nil : combined.uppercased()
}

func normalizedPhone(_ phone: String) -> String {
    return phone.filter { "0123456789".contains($0) }
}

func lookupContact(handle: String) -> ContactResult {
    let store = CNContactStore()

    let keysToFetch: [CNKeyDescriptor] = [
        CNContactGivenNameKey as NSString,
        CNContactFamilyNameKey as NSString,
        CNContactNicknameKey as NSString,
        CNContactImageDataKey as NSString,
        CNContactPhoneNumbersKey as NSString,
        CNContactEmailAddressesKey as NSString
    ]

    let request = CNContactFetchRequest(keysToFetch: keysToFetch)

    var matchedContact: CNContact? = nil

    do {
        try store.enumerateContacts(with: request) { contact, stop in
            if handle.contains("@") {
                for email in contact.emailAddresses {
                    let value = email.value as String
                    if value.caseInsensitiveCompare(handle) == .orderedSame {
                        matchedContact = contact
                        stop.pointee = true
                        return
                    }
                }
            } else {
                let target = normalizedPhone(handle)
                if target.isEmpty { return }

                for number in contact.phoneNumbers {
                    let value = number.value.stringValue
                    let normalized = normalizedPhone(value)
                    // Match if digits are equal, or if one is suffix of other (handle country codes)
                    if normalized == target ||
                       normalized.hasSuffix(target) ||
                       target.hasSuffix(normalized) {
                        matchedContact = contact
                        stop.pointee = true
                        return
                    }
                }
            }
        }
    } catch {
        // Fall through and return empty result
    }

    guard let contact = matchedContact else {
        return ContactResult(
            handle: handle,
            name: nil,
            givenName: nil,
            familyName: nil,
            nickname: nil,
            initials: nil,
            hasImage: false,
            imageBase64: nil
        )
    }

    let formatter = CNContactFormatter()
    formatter.style = .fullName
    let fullName = formatter.string(from: contact)

    var imageB64: String? = nil
    var hasImage = false
    if let data = contact.imageData {
        imageB64 = data.base64EncodedString()
        hasImage = true
    }

    return ContactResult(
        handle: handle,
        name: fullName,
        givenName: contact.givenName.isEmpty ? nil : contact.givenName,
        familyName: contact.familyName.isEmpty ? nil : contact.familyName,
        nickname: contact.nickname.isEmpty ? nil : contact.nickname,
        initials: initials(from: contact),
        hasImage: hasImage,
        imageBase64: imageB64
    )
}

func main() {
    let args = CommandLine.arguments
    guard args.count >= 2 else {
        fputs("usage: contact_lookup <phone-or-email>\n", stderr)
        exit(1)
    }

    let handle = args[1]
    let result = lookupContact(handle: handle)

    let encoder = JSONEncoder()
    if #available(macOS 10.13, *) {
        encoder.outputFormatting = [.sortedKeys]
    }

    do {
        let data = try encoder.encode(result)
        if let json = String(data: data, encoding: .utf8) {
            print(json)
        } else {
            fputs("failed to encode json as utf-8\n", stderr)
            exit(1)
        }
    } catch {
        fputs("failed to encode json: \(error)\n", stderr)
        exit(1)
    }
}

main()
