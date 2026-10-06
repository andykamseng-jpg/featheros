# Feather PC Registry

Private device roster for Feather Prep. Device records are stored in a **private** Vercel Blob store. The page itself contains no device records; its list API requires `REGISTRY_ADMIN_KEY`. No disk serials, user accounts, file names, or unique network device instance paths are accepted.

## Vercel setup

1. Connect a private Blob store to the `featheros` Vercel project.
2. Add `REGISTRY_ADMIN_KEY` as an encrypted production environment variable (at least 32 random bytes, hex-encoded).
3. Make the production `.vercel.app` deployment reachable by computers so they can use the check-in endpoint. The PC list API remains locked behind `REGISTRY_ADMIN_KEY`.
4. Deploy this directory as the project root. Feather Prep 0.6.3 defaults to `https://featheros.vercel.app`; `FEATHER_REGISTRY_URL` can override it for another deployment.

The Windows launcher scans and sends a bounded report by default after installation; users can turn off sharing in its window. A device generates its own random ID and write token; the server stores only a hash of the token. Device reports include the computer name, model, OS, firmware and board details, general graphics/network vendor and product IDs, and up to 200 installed driver names, versions, providers and signing flags. Unchecking sharing removes that PC's record. The readiness state remains blocked until a tested bootable FeatherOS image and matching OS drivers are available.

Vercel Blob is free within the Hobby plan's published usage allowance. This registry writes one small private JSON object per opted-in PC and is suitable for a small personal/test fleet. See Vercel's current Blob pricing and private storage documentation before expanding it to a public product.
