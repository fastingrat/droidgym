{
  description = "DroidGym";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    android-nixpkgs.url = "github:tadfisher/android-nixpkgs";
  };

  outputs =
    {
      self,
      nixpkgs,
      android-nixpkgs,
      ...
    }:
    let
      system = "aarch64-darwin";
      pkgs = import nixpkgs { inherit system; };

      sdk = android-nixpkgs.sdk.${system} (
        sdkPkgs: with sdkPkgs; [
          cmdline-tools-latest
          platform-tools
          emulator
          system-images-android-33-google-apis-arm64-v8a
        ]
      );
    in
    {
      devShells.${system}.default = pkgs.mkShell {

        buildInputs = [
          sdk
          pkgs.python311
          pkgs.scrcpy
        ];

        shellHook = ''
          export NIX_SHELL_NAME="DG"
        '';
      };
    };
}
