import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.Signature;
import java.security.interfaces.ECPublicKey;
import java.security.spec.ECGenParameterSpec;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.time.Instant;
import java.util.Base64;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 索引签名工具（JDK 17 单文件运行，无第三方依赖）。
 *
 * 用法：
 *   java IndexSignatureTool.java keygen --private D:\keys\index-private.pem --public keys/index-2026-11.pem
 *   java IndexSignatureTool.java sign --registry registry.json --key D:\keys\index-private.pem \
 *        --key-id index-2026-11 --out registry.sig
 *   java IndexSignatureTool.java verify --registry registry.json --signature registry.sig \
 *        --public keys/index-2026-11.pem
 */
public final class IndexSignatureTool {
    private static final int SCHEMA = 1;
    private static final String ALGORITHM = "ECDSA_P256_SHA256";
    private static final String PAYLOAD_PREFIX = "lifehub-index-v1";
    private static final Pattern KEY_ID = Pattern.compile("^[A-Za-z0-9._-]+$");

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            usage();
            System.exit(2);
        }
        switch (args[0]) {
            case "keygen" -> keygen(args);
            case "sign" -> sign(args);
            case "verify" -> verify(args);
            default -> {
                usage();
                System.exit(2);
            }
        }
    }

    private static void keygen(String[] args) throws Exception {
        Args parsed = Args.parse(args, 1);
        Path privatePath = parsed.requiredPath("--private");
        Path publicPath = parsed.requiredPath("--public");

        KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
        generator.initialize(new ECGenParameterSpec("secp256r1"));
        KeyPair keyPair = generator.generateKeyPair();

        writePem(privatePath, "PRIVATE KEY", keyPair.getPrivate().getEncoded());
        writePem(publicPath, "PUBLIC KEY", keyPair.getPublic().getEncoded());

        System.out.println("private=" + privatePath);
        System.out.println("public=" + publicPath);
        System.out.println("publicSha256=" + sha256Hex(keyPair.getPublic().getEncoded()));
    }

    private static void sign(String[] args) throws Exception {
        Args parsed = Args.parse(args, 1);
        Path registry = parsed.requiredPath("--registry");
        Path keyPath = parsed.requiredPath("--key");
        Path output = parsed.requiredPath("--out");
        String keyId = parsed.required("--key-id");
        if (!KEY_ID.matcher(keyId).matches()) {
            throw new IllegalArgumentException("keyId 只能包含字母、数字、点、下划线和连字符");
        }

        byte[] registryBytes = Files.readAllBytes(registry);
        String registrySha256 = sha256Hex(registryBytes);
        PrivateKey privateKey = readPrivateKey(keyPath);

        Signature signer = Signature.getInstance("SHA256withECDSA");
        signer.initSign(privateKey);
        signer.update(payload(registrySha256));
        String signature = Base64.getEncoder().encodeToString(signer.sign());

        String json = "{\n"
                + "  \"schema\": " + SCHEMA + ",\n"
                + "  \"algorithm\": \"" + ALGORITHM + "\",\n"
                + "  \"keyId\": \"" + keyId + "\",\n"
                + "  \"registrySha256\": \"" + registrySha256 + "\",\n"
                + "  \"signature\": \"" + signature + "\",\n"
                + "  \"signedAt\": \"" + Instant.now().toString() + "\"\n"
                + "}\n";
        Files.createDirectories(output.toAbsolutePath().getParent());
        Files.writeString(output, json, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
        System.out.println("signed=" + output);
        System.out.println("registrySha256=" + registrySha256);
    }

    private static void verify(String[] args) throws Exception {
        Args parsed = Args.parse(args, 1);
        Path registry = parsed.requiredPath("--registry");
        Path signaturePath = parsed.requiredPath("--signature");
        Path publicPath = parsed.requiredPath("--public");

        String json = Files.readString(signaturePath, StandardCharsets.UTF_8);
        int schema = Integer.parseInt(requiredField(json, "schema", true));
        String algorithm = requiredField(json, "algorithm", false);
        String registrySha256 = requiredField(json, "registrySha256", false);
        String signatureText = requiredField(json, "signature", false);
        if (schema != SCHEMA) throw new IllegalStateException("不支持的签名 schema：" + schema);
        if (!ALGORITHM.equals(algorithm)) throw new IllegalStateException("不支持的签名算法：" + algorithm);

        byte[] registryBytes = Files.readAllBytes(registry);
        String actual = sha256Hex(registryBytes);
        if (!actual.equals(registrySha256)) {
            throw new IllegalStateException("registry.json 摘要与签名不一致");
        }

        PublicKey publicKey = readPublicKey(publicPath);
        Signature verifier = Signature.getInstance("SHA256withECDSA");
        verifier.initVerify(publicKey);
        verifier.update(payload(registrySha256));
        if (!verifier.verify(Base64.getDecoder().decode(signatureText))) {
            throw new IllegalStateException("索引签名校验失败");
        }
        System.out.println("verified registrySha256=" + registrySha256);
    }

    private static byte[] payload(String registrySha256) {
        return (PAYLOAD_PREFIX + "\n" + registrySha256).getBytes(StandardCharsets.UTF_8);
    }

    private static PrivateKey readPrivateKey(Path path) throws Exception {
        String base64 = readPem(path, "PRIVATE KEY");
        return KeyFactory.getInstance("EC")
                .generatePrivate(new PKCS8EncodedKeySpec(Base64.getDecoder().decode(base64)));
    }

    private static PublicKey readPublicKey(Path path) throws Exception {
        String base64 = readPem(path, "PUBLIC KEY");
        PublicKey key = KeyFactory.getInstance("EC")
                .generatePublic(new X509EncodedKeySpec(Base64.getDecoder().decode(base64)));
        ECPublicKey ecKey = (ECPublicKey) key;
        if (ecKey.getParams().getCurve().getField().getFieldSize() != 256) {
            throw new IllegalStateException("公钥必须是 P-256 曲线");
        }
        return key;
    }

    private static String readPem(Path path, String label) throws IOException {
        String text = Files.readString(path, StandardCharsets.UTF_8);
        String begin = "-----BEGIN " + label + "-----";
        String end = "-----END " + label + "-----";
        int start = text.indexOf(begin);
        int finish = text.indexOf(end);
        if (start < 0 || finish < 0 || finish <= start) {
            throw new IllegalArgumentException("不是有效的 PEM 文件：" + path);
        }
        return text.substring(start + begin.length(), finish).replaceAll("\\s", "");
    }

    private static void writePem(Path path, String label, byte[] der) throws IOException {
        Files.createDirectories(path.toAbsolutePath().getParent());
        String base64 = Base64.getMimeEncoder(64, new byte[]{'\n'}).encodeToString(der);
        String pem = "-----BEGIN " + label + "-----\n" + base64
                + "\n-----END " + label + "-----\n";
        Files.writeString(path, pem, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
    }

    private static String requiredField(String json, String field, boolean numeric) {
        String pattern = numeric
                ? "\"" + field + "\"\\s*:\\s*(\\d+)"
                : "\"" + field + "\"\\s*:\\s*\"([^\"]+)\"";
        Matcher matcher = Pattern.compile(pattern).matcher(json);
        if (!matcher.find()) {
            throw new IllegalArgumentException("签名缺少字段：" + field);
        }
        return matcher.group(1);
    }

    private static String sha256Hex(byte[] bytes) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder builder = new StringBuilder(digest.length * 2);
        for (byte value : digest) {
            builder.append(String.format("%02x", value));
        }
        return builder.toString();
    }

    private static void usage() {
        System.out.println("java IndexSignatureTool.java keygen --private <pem> --public <pem>");
        System.out.println("java IndexSignatureTool.java sign --registry <json> --key <pem> --key-id <id> --out <sig>");
        System.out.println("java IndexSignatureTool.java verify --registry <json> --signature <sig> --public <pem>");
    }

    private record Args(String[] args) {
        static Args parse(String[] args, int start) {
            return new Args(java.util.Arrays.copyOfRange(args, start, args.length));
        }

        String required(String name) {
            for (int i = 0; i < args.length - 1; i++) {
                if (name.equals(args[i])) return args[i + 1];
            }
            throw new IllegalArgumentException("缺少参数：" + name);
        }

        Path requiredPath(String name) {
            return Path.of(required(name));
        }
    }
}
